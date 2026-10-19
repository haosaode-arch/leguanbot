# -*- coding: utf-8 -*-
"""小游戏：骰子、抛硬币、猜拳、随机点人。"""

import random
import time

from telegram import Update
from telegram.ext import ContextTypes

import database as db

RPS_MAP = {"石头": "rock", "剪刀": "scissors", "布": "paper"}
RPS_EMOJI = {"rock": "✊ 石头", "scissors": "✌️ 剪刀", "paper": "🖐️ 布"}
WIN_RULES = {"rock": "scissors", "scissors": "paper", "paper": "rock"}

RPS_WIN = 80   # 猜拳赢的奖励
RPS_LOSE = 50  # 猜拳输的惩罚

DICE_FACES = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
MAX_DICE = 10

# ---------- 随机点人：记录各群最近 10 分钟内发过言的真人 ----------

ACTIVE_TTL = 10 * 60  # 秒
_recent_active = {}  # chat_id -> {user_id: (User对象, 时间戳)}
_last_picked = {}    # chat_id -> [最近被点过的 uid，避免连续点到同一人]


def record_activity(update: Update):
    """在消息处理器入口调用，记录活跃用户（只记已授权群）。"""
    chat, user = update.effective_chat, update.effective_user
    if user is None or user.is_bot or chat.type not in ("group", "supergroup"):
        return
    if not db.is_chat_authorized(chat.id):
        return
    bucket = _recent_active.setdefault(chat.id, {})
    bucket[user.id] = (user, time.time())
    # 清理过期记录
    now = time.time()
    for uid in [u for u, (_, ts) in bucket.items() if now - ts > ACTIVE_TTL]:
        bucket.pop(uid, None)


# ---------- 指令 ----------

async def cmd_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/骰子 [数量] —— 掷 N 个六面骰子。"""
    count = 1
    if context.args:
        try:
            count = int(context.args[0])
        except ValueError:
            pass
    count = max(1, min(count, MAX_DICE))

    rolls = [random.randint(1, 6) for _ in range(count)]
    emojis = " ".join(DICE_FACES[r - 1] for r in rolls)
    total = sum(rolls)
    suffix = f" = {total}" if count > 1 else ""
    await update.message.reply_text(f"🎲 {emojis}{suffix}")


async def cmd_coin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/硬币 —— 抛硬币。"""
    result = random.choice(["正面 🌕", "反面 🌑"])
    await update.message.reply_text(f"🪙 硬币转动中……\n结果是：{result}！")


async def cmd_rps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/猜拳 石头|剪刀|布 —— 与机器人猜拳，带小额赌注。"""
    user = update.effective_user

    if not context.args or context.args[0] not in RPS_MAP:
        await update.message.reply_text(
            "用法：/猜拳 石头｜剪刀｜布\n"
            f"{RPS_WIN} 金币起注：赢 +{RPS_WIN}，输 -{RPS_LOSE} 哦～"
        )
        return

    mine = RPS_MAP[context.args[0]]
    bot_choice = random.choice(list(RPS_MAP.values()))
    row = db.ensure_user(user.id)

    if bot_choice == mine:
        await update.message.reply_text(
            f"你出 {RPS_EMOJI[mine]}，我出 {RPS_EMOJI[bot_choice]}\n"
            "平局！不下注，再来一把 😉"
        )
        return

    if WIN_RULES[mine] == bot_choice:
        db.add_points(user.id, RPS_WIN)
        db.update_user(
            user.id, wins=row["wins"] + 1, username=user.username, first_name=user.first_name
        )
        result_text = f"你赢了！ +{RPS_WIN} 金币 🎉"
    else:
        db.add_points(user.id, -RPS_LOSE)
        db.update_user(
            user.id, losses=row["losses"] + 1, username=user.username, first_name=user.first_name
        )
        result_text = f"你输了… -{RPS_LOSE} 金币 😭"

    await update.message.reply_text(
        f"你出 {RPS_EMOJI[mine]}，我出 {RPS_EMOJI[bot_choice]}\n{result_text}"
    )


async def cmd_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/点人 [问题] —— 随机 @ 一个最近活跃的群友。"""
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("这个命令只能在群里用哦～")
        return

    bucket = _recent_active.get(chat.id, {})
    if not bucket:
        await update.message.reply_text(
            "最近 10 分钟没人发言，我点不到人 😢"
        )
        return

    # 尽量避开最近 3 次已被点过的人（样本太小时不排除）
    candidates = [u for u in bucket.values() if u[0].id not in _last_picked.get(chat.id, [])]
    if not candidates:
        candidates = list(bucket.values())
        _last_picked[chat.id] = []

    victim, _ = random.choice(candidates)
    picked = _last_picked.setdefault(chat.id, [])
    picked.append(victim.id)
    if len(picked) > 3:
        picked.pop(0)
    mention = victim.mention_html()
    question = " ".join(context.args) if context.args else ""
    if question:
        text = f"🎯 命中！ {mention} 请你回答：\n«{question}»"
    else:
        text = f"🎯 命中！ 就是 {mention} 你了！"
    await update.message.reply_text(text, parse_mode="HTML")
