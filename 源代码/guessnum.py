# -*- coding: utf-8 -*-
"""猜数字

/猜数字                 —— 出一个 1~999 的数（或查看当前进度）
/猜数字 500             —— 在群里猜
/猜                     —— 同上的简写
/猜数字 结束            ——（bot 管理员/群管理员）结束

机器人自动收窄提示范围；首个猜中者 +30 金币（每人每天最多 3 次），
猜中后自动开下一局。
"""

import html
import random

from telegram import Update
from telegram.ext import ContextTypes

import database as db

REWARD = 30
DAILY_CAP = 3
MAX_TARGET = 999

GAMES = {}  # chat_id -> {"target": int, "low": int, "high": int}


def _new(chat_id):
    target = random.randint(1, MAX_TARGET)
    GAMES[chat_id] = {"target": target, "low": 1, "high": MAX_TARGET}
    return target


async def _is_chat_admin(user, chat_id, context) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


async def cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("猜数字只能在群里玩哦～")
        return

    user = update.effective_user
    arg = " ".join(context.args or []).strip()
    state = GAMES.get(chat.id)

    # 结束
    if arg == "结束":
        if state and (db.is_bot_admin(user.id) or await _is_chat_admin(user, chat.id, context)):
            GAMES.pop(chat.id, None)
            await update.message.reply_text("🏁 猜数字已结束（答案是 … 不告诉你 😜）。发 /猜数字 再开。")
        else:
            await update.message.reply_text("只有 bot 管理员或群管理员能结束。")
        return

    # 猜测
    if arg.isdigit():
        num = int(arg)
        if state is None:
            _new(chat.id)
            state = GAMES[chat.id]
        if num > MAX_TARGET or num < 1:
            await update.message.reply_text(f"范围是 1 ~ {MAX_TARGET} 哦～")
            return

        target = state["target"]

        if num == target:
            name = html.escape(user.first_name or "群友")
            day = db.today_cn()
            won = db.daily_wins_count(user.id, "guessnum", day)
            if won < DAILY_CAP:
                db.add_points(user.id, REWARD)
                db.add_daily_win(user.id, "guessnum", day)
                note = f"🎁 +{REWARD} 金币（今日第 {won + 1}/{DAILY_CAP} 次）"
            else:
                note = f"😅 今日 {DAILY_CAP} 次奖励领完，纯娱乐！"
            new_target = random.randint(1, MAX_TARGET)
            GAMES[chat.id] = {"target": new_target, "low": 1, "high": MAX_TARGET}
            await update.message.reply_text(
                f"🎉 {name} 猜中了！答案是 {target}！\n{note}\n\n"
                f"🔄 新一局已自动开始！范围 1 ~ {MAX_TARGET}，快发 /猜 数字！"
            )
        elif num < target:
            state["low"] = max(state["low"], num + 1)
            await update.message.reply_text(
                f"📈 {num} 小了！范围收窄为 {state['low']} ~ {state['high']}"
            )
        else:
            state["high"] = min(state["high"], num - 1)
            await update.message.reply_text(
                f"📉 {num} 大了！范围收窄为 {state['low']} ~ {state['high']}"
            )
        return

    # 无参：开新局或展示进度
    if state is None:
        _new(chat.id)
        await update.message.reply_text(
            f"🎯 猜数字开始！我心里想了一个 1 ~ {MAX_TARGET} 的整数。\n"
            f"群里发 /猜数字 数字 来猜，提示自动收窄。\n"
            f"猜中奖励 {REWARD} 金币，每人每天最多 {DAILY_CAP} 次。"
        )
    else:
        await update.message.reply_text(
            f"🎯 进行中！当前范围 {state['low']} ~ {state['high']}\n发 /猜数字 数字 来猜～"
        )
