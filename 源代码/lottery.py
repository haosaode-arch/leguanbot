# -*- coding: utf-8 -*-
"""群抽奖 / 俄罗斯轮盘。内存态，按聊天区分。"""

import random
import re
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
import economy

MAX_MINUTES = 30

# chat_id -> {"prize": str, "ends": float, "msg_id": int, "players": {uid: name}}
LOTTERIES = {}
# chat_id -> {"prize": str, "msg_id": int, "players": {uid: name}, "target": int, "alive": set}
ROULETTES = {}


def _fmt_name(user_id, name):
    return name or f"用户{user_id}"


def _parse_prize(prize: str):
    """统一解析：返回 (gold, custom, display)。display 始终是用户写的原文。"""
    gold, custom = economy.parse_reward(prize or "")
    return gold, custom, (prize or "100金币")


# ============ 抽奖 ============

async def cmd_lottery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/抽奖 [奖品] [持续分钟]，默认 1 分钟、奖品 100金币。"""
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("抽奖只能在群里发起哦～")
        return
    if chat.id in LOTTERIES:
        await update.message.reply_text("本群已有一个进行中的抽奖，先等它开奖！")
        return

    user = update.effective_user
    args = context.args or []
    minutes = 1.0
    if len(args) >= 2:
        try:
            minutes = float(args[-1])
        except ValueError:
            minutes = 1.0
        args = args[:-1]
    minutes = max(0.2, min(minutes, MAX_MINUTES))
    prize = " ".join(args) if args else "100金币"

    gold, custom, display_prize = _parse_prize(prize)
    if gold is not None:
        row = db.ensure_user(user.id)
        if row["points"] < gold:
            await update.message.reply_text(
                f"你的金币不够发「{gold} 金币」的奖，当前只有 {row['points']}。"
            )
            return
        # 先冻结发起者金币，开奖时到场发放；无人参与则退还
        db.add_points(user.id, -gold)

    ends = time.time() + minutes * 60
    LOTTERIES[chat.id] = {
        "prize": display_prize,
        "ends": ends,
        "msg_id": None,
        "players": {},
        "starter": user.id,
        "gold": gold,
        "custom": custom,
    }

    text = (
        f"🎉 抽奖开始！\n"
        f"🎁 奖品：{display_prize}\n"
        f"⏰ {int(minutes)} 分钟后自动开奖\n"
        f"👥 当前 {0} 人参加\n\n"
        "点下面的按钮参加！"
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🙋 我要参加", callback_data="lotjoin")]]
    )
    msg = await update.message.reply_text(text, reply_markup=keyboard)
    LOTTERIES[chat.id]["msg_id"] = msg.message_id

    context.job_queue.run_once(_end_lottery, minutes * 60, chat_id=chat.id, name="lottery", data=chat.id)


async def cb_lot_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    state = LOTTERIES.get(chat_id)
    if not state:
        await query.answer("这场抽奖已经结束啦", show_alert=True)
        return

    user = query.from_user
    if user.id in state["players"]:
        await query.answer("你已经加入过了～")
        return

    state["players"][user.id] = user.first_name or user.username or str(user.id)
    await query.answer("报名成功！祈愿好运吧🍀")

    seconds_left = max(0, int(state["ends"] - time.time()))
    text = (
        f"🎉 抽奖进行中…\n"
        f"🎁 奖品：{state['prize']}\n"
        f"👥 当前 {len(state['players'])} 人参加\n"
        f"⏰ 约 {seconds_left // 60} 分 {seconds_left % 60} 秒后开奖"
    )
    try:
        await query.edit_message_text(text, reply_markup=query.message.reply_markup)
    except Exception:
        pass


async def _end_lottery(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    state = LOTTERIES.pop(chat_id, None)
    if not state:
        return
    players = state["players"]
    if not players:
        if state.get("gold") is not None:  # 没人参加时退还发起者被冻结的金币
            db.add_points(state.get("starter", 0), state["gold"])
        await context.bot.send_message(chat_id, "😢 没有人参加抽奖，奖品已退还发起者……")
        return

    winner_id = random.choice(list(players.keys()))
    winner_name = _fmt_name(winner_id, players[winner_id])

    gold = state.get("gold")
    custom = state.get("custom", "")
    if gold is not None:
        db.add_points(winner_id, gold)
    notes = []
    if gold is not None:
        notes.append(f"💰 {gold} 金币已存入 TA 的钱包")
    if custom:
        notes.append(f"🧾 额外奖励：{custom}（请找发起者兑换）")
    if not notes:
        prize_note = f"🎁 奖品：{state['prize']}，速速找发起者兑奖！"
    else:
        prize_note = "\n".join(notes)

    await context.bot.send_message(
        chat_id,
        f"🎊 开奖啦！\n🏆 恭喜 <b>{winner_name}</b> 中奖！\n{prize_note}",
        parse_mode="HTML",
    )


# ============ 俄罗斯轮盘 ============

async def cmd_roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/轮盘 [奖品] [人数]，默认 100金币、3 人。人满即开枪淘汰。"""
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("轮盘只能在群里玩哦～")
        return
    if chat.id in ROULETTES:
        await update.message.reply_text("本群已有一局轮盘在进行中！")
        return

    user = update.effective_user
    args = context.args or []
    target = 3
    if len(args) >= 2:
        try:
            target = int(args[-1])
        except ValueError:
            target = 3
        args = args[:-1]
    target = max(2, min(target, 20))
    prize = " ".join(args) if args else "100金币"

    gold, custom, display_prize = _parse_prize(prize)
    if gold is not None:
        row = db.ensure_user(user.id)
        if row["points"] < gold:
            await update.message.reply_text(
                f"你的金币不够设置「{gold} 金币」的奖池，当前只有 {row['points']}。"
            )
            return
        db.add_points(user.id, -gold)

    ROULETTES[chat.id] = {
        "prize": display_prize,
        "gold": gold,
        "custom": custom,
        "target": target,
        "msg_id": None,
        "players": {},
        "starter": user.id,
    }

    text = (
        f"🔫 俄罗斯轮盘开局！\n"
        f"🎁 奖池：{display_prize}\n"
        f"⚠️ 需要 {target} 人参加，人满自动开枪，每轮随机淘汰 1 人，活到最后的人独吞奖池"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🎯 上桌", callback_data="roujoin")]])
    msg = await update.message.reply_text(text, reply_markup=keyboard)
    ROULETTES[chat.id]["msg_id"] = msg.message_id

    # 10 分钟内凑不齐人则自动取消并退款
    context.job_queue.run_once(
        _roulette_cancel, 10 * 60, chat_id=chat.id, name="rou_cancel", data=chat.id
    )


async def _roulette_cancel(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    state = ROULETTES.get(chat_id)
    if not state:
        return
    ROULETTES.pop(chat_id, None)
    if state.get("gold") is not None:
        db.add_points(state.get("starter", 0), state["gold"])
    await context.bot.send_message(
        chat_id,
        f"⏰ 轮盘 10 分钟内未凑齐 {state['target']} 人，本局取消，奖池已退还发起者。",
    )


async def cb_rou_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    state = ROULETTES.get(chat_id)
    if not state:
        await query.answer("这一局已经结束了", show_alert=True)
        return

    user = query.from_user
    if user.id in state["players"]:
        await query.answer("你已经在桌上了！")
        return
    if len(state["players"]) >= state["target"]:
        await query.answer("人满了，等下一局吧", show_alert=True)
        return

    state["players"][user.id] = user.first_name or user.username or str(user.id)
    now_n = len(state["players"])
    await query.answer(f"就位！当前 {now_n}/{state['target']} 人")

    try:
        await query.edit_message_text(
            f"🔫 俄罗斯轮盘\n🎁 奖池：{state['prize']}\n"
            f"👤 坐席 {now_n}/{state['target']}\n子弹随时上膛……",
            reply_markup=None if now_n >= state["target"] else query.message.reply_markup,
        )
    except Exception:
        pass

    if now_n >= state["target"]:
        # 人满：3 秒后开始依次淘汰
        context.job_queue.run_once(_roulette_tick, 3, chat_id=chat_id, name="rou", data=chat_id)


async def _roulette_tick(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    state = ROULETTES.get(chat_id)
    if not state:
        return

    alive = list(state["players"].items())
    if len(alive) <= 1:
        ROULETTES.pop(chat_id, None)
        wid, wname = alive[0]
        gold, custom = state.get("gold"), state.get("custom", "")
        if gold is not None:
            db.add_points(wid, gold)
        notes = []
        if gold is not None:
            notes.append(f"💰 {gold} 金币已到账！")
        if custom:
            notes.append(f"🧾 额外奖励：{custom}（请找发起者兑换）")
        if not notes:
            notes.append(f"🎁 奖品：{state['prize']}")
        await context.bot.send_message(
            chat_id,
            f"🔫 枪声停止……\n🏆 生存者：<b>{_fmt_name(wid, wname)}</b>\n" + "\n".join(notes),
            parse_mode="HTML",
        )
        return

    victim_id, victim_name = random.choice(alive)
    state["players"].pop(victim_id)
    await context.bot.send_message(
        chat_id,
        f"💥 砰！<b>{_fmt_name(victim_id, victim_name)}</b> 被淘汰，黯然离场（存活 {len(state['players'])} 人）",
        parse_mode="HTML",
    )

    context.job_queue.run_once(
        _roulette_tick, random.uniform(1.5, 2.5), chat_id=chat_id, name="rou", data=chat_id
    )
