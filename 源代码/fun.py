# -*- coding: utf-8 -*-
"""小游戏：骰子、抛硬币、猜拳、随机点人。"""

import random
import re
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

STAKE_MIN, STAKE_MAX = 10, 10000


async def _stake_from_args(context) -> int:
    """从参数解析押注：'押100' / '100金币' → 金币数；'3' 这类纯数字返回 0（按骰子颗数理解）。"""
    arg = "".join(context.args or []).strip()
    if not arg:
        return 0
    if arg.isdigit():
        return 0  # 骰子的旧用法：数字 = 颗数
    m = re.search(r"押\s*(\d+)|(\d+)\s*金币", arg)
    if not m:
        return 0
    return max(STAKE_MIN, min(int(m.group(1) or m.group(2)), STAKE_MAX))


async def cmd_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/骰子 [数量] —— 掷骰子；/骰子 押100 —— 压单颗骰子：≥4 赢等额，≤3 输等额。"""
    user = update.effective_user
    stake = await _stake_from_args(context)
    chat = update.effective_chat

    # ---- 押注玩法（单颗真·TG 骰子动画，≥4 点赢） ----
    if stake:
        row = db.ensure_user(user.id)
        if row["points"] < stake:
            await update.message.reply_text(
                f"💰 金币不够押（当前 {row['points']}，要 {STAKE_MIN}~{STAKE_MAX} 的押注），先 /签到 攒一攒～"
            )
            return
        dice_msg = await context.bot.send_dice(chat.id, emoji="🎲")
        import asyncio
        await asyncio.sleep(1.2)
        v = dice_msg.dice.value
        if v >= 4:
            db.add_points(user.id, stake)
            db.update_user(user.id, wins=row["wins"] + 1, username=user.username, first_name=user.first_name)
            await update.message.reply_text(f"🎲 掷出 {v} 点（≥4）—— 赢了！ +{stake} 金币 🎉")
        else:
            db.add_points(user.id, -stake)
            db.update_user(user.id, losses=row["losses"] + 1, username=user.username, first_name=user.first_name)
            await update.message.reply_text(f"🎲 掷出 {v} 点（≤3）—— 输了… -{stake} 金币 😭")
        return

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
    """/硬币 —— 抛硬币；/硬币 押100 —— 押正面：正面赢等额，反面输等额。"""
    user = update.effective_user
    stake = await _stake_from_args(context)

    if stake:
        row = db.ensure_user(user.id)
        if row["points"] < stake:
            await update.message.reply_text(
                f"💰 金币不够押（当前 {row['points']}），先 /签到 攒一攒～"
            )
            return
        result = random.choice(["正面", "反面"])
        face = "🌕" if result == "正面" else "🌑"
        if result == "正面":
            db.add_points(user.id, stake)
            db.update_user(user.id, wins=row["wins"] + 1, username=user.username, first_name=user.first_name)
            verdict = f"押正面 ✅ —— 赢了！ +{stake} 金币 🎉"
        else:
            db.add_points(user.id, -stake)
            db.update_user(user.id, losses=row["losses"] + 1, username=user.username, first_name=user.first_name)
            verdict = f"押正面 ❌（开的是反面）—— 输了… -{stake} 金币 😭"
        await update.message.reply_text(
            f"🪙 硬币转动中……\n开奖：{result} {face}\n{verdict}"
        )
        return

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
