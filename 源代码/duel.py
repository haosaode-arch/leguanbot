# -*- coding: utf-8 -*-
"""约战决斗

回复某个人的消息并发 /决斗 [押注]（默认 100）→ 对方点【应战】按钮 →
双方各掷一枚真·Telegram 骰子（🎲 动画），点数大者独吞奖池（2×押注）。
押注在【应战】成功时才扣款，不应战/超时双方零损失。
"""

import asyncio
import html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
import economy

MIN_STAKE = 50
MAX_STAKE = 10000
EXPIRE = 120  # 秒

# chat_id -> {"challenger": uid, "target": uid, "stake": int, "msg_id": int,
#             "challenger_name": str, "target_name": str}
PENDING = {}


async def cmd_duel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("决斗只能在群里发起哦～")
        return

    user = update.effective_user
    reply = update.message.reply_to_message

    # 目标：回复被挑战者消息
    if not (reply and reply.from_user and not reply.from_user.is_bot):
        await update.message.reply_text("用法：回复想挑战的人的消息，发送 /决斗 押注（默认 100）")
        return
    target = reply.from_user
    if target.id == user.id:
        await update.message.reply_text("和自己决斗？😅 换个人挑战吧。")
        return
    if chat.id in PENDING:
        await update.message.reply_text("本群已有一场决斗待应战，先完成它！")
        return

    stake_text = context.args[0] if context.args else "100"
    gold, custom = economy.parse_reward(stake_text)
    stake = gold if gold else MIN_STAKE
    if custom:
        await update.message.reply_text("决斗押注只支持金币，别用自定义奖励哦～")
        return
    stake = max(MIN_STAKE, min(stake, MAX_STAKE))

    row = db.ensure_user(user.id)
    if row["points"] < stake:
        await update.message.reply_text(f"你自己的金币不够 {stake}（当前 {row['points']}），先去 /签到 吧～")
        return
    trow = db.ensure_user(target.id)
    if trow["points"] < stake:
        await update.message.reply_text(
            f"对方金币不够 {stake}（当前 {trow['points']}），换个小注吧。"
        )
        return

    PENDING[chat.id] = {
        "challenger": user.id,
        "target": target.id,
        "stake": stake,
        "challenger_name": user.first_name or "挑战者",
        "target_name": target.first_name or "应战者",
    }
    text = (
        f"⚔️ <b>{html.escape(user.first_name)}</b> 向 "
        f"<b>{html.escape(target.first_name)}</b> 发起决斗！\n"
        f"💰 押注：{stake} 金币 ×2 = {stake * 2} 赢家通吃\n"
        f"⏳ {EXPIRE // 60} 分钟内点按钮应战，不应战无任何损失"
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⚔️ 应战！", callback_data=f"duelok:{chat.id}")]]
    )
    msg = await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    PENDING[chat.id]["msg_id"] = msg.message_id

    context.job_queue.run_once(_expire, EXPIRE, chat_id=chat.id, name="duel_expire", data=chat.id)


async def _expire(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    state = PENDING.pop(chat_id, None)
    if not state:
        return
    try:
        await context.bot.edit_message_text(
            f"⌛ 决斗邀约超时作废（{state['stake']} 金币无人应战）。",
            chat_id=chat_id, message_id=state["msg_id"],
        )
    except Exception:
        pass


async def cb_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = int(query.data.split(":", 1)[1])
    if not db.is_chat_authorized(chat_id):
        await query.answer("本群未获得使用授权", show_alert=True)
        return
    state = PENDING.get(chat_id)
    if not state:
        await query.answer("这场决斗已经超时或结束了", show_alert=True)
        return
    if query.from_user.id != state["target"]:
        await query.answer("只有被挑战的人才能应战哦～")
        return
    if not PENDING.pop(chat_id, None):
        await query.answer("晚了…", show_alert=True)
        return

    challenger_id = state["challenger"]
    stake = state["stake"]
    if db.ensure_user(challenger_id)["points"] < stake or db.ensure_user(acceptor.id)["points"] < stake:
        await query.answer("有一方金币不够了，决斗取消。", show_alert=True)
        return
    db.add_points(challenger_id, -stake)
    db.add_points(acceptor.id, -stake)

    # 双方各掷一枚真 Telegram 骰子，平点重掷
    v1 = v2 = 0
    dices = []
    while v1 == v2:
        d1 = await context.bot.send_dice(chat_id, emoji="🎲")
        d2 = await context.bot.send_dice(chat_id, emoji="🎲")
        v1, v2 = d1.dice.value, d2.dice.value
        dices = [d1, d2]

    if v1 > v2:
        winner_id, loser_id, wv, lv = challenger_id, acceptor.id, v1, v2
        winner_name = state["challenger_name"]
    else:
        winner_id, loser_id, wv, lv = acceptor.id, challenger_id, v2, v1
        winner_name = state["target_name"]
    winner_name = html.escape(winner_name)
    db.add_points(winner_id, stake * 2)

    await asyncio.sleep(1.2)  # 等骰子动画落地
    await context.bot.send_message(
        chat_id,
        f"⚔️ 决斗双方掷骰：🎲 {v1} 对 🎲 {v2}\n"
        f"🏆 <b>{winner_name}</b> 以 {wv} 比 {lv} 获胜！\n"
        f"💰 独吞奖池 {stake * 2} 金币！",
        parse_mode="HTML",
    )
