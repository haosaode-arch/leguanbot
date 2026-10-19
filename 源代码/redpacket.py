# -*- coding: utf-8 -*-
"""红包：/红包 奖励 [份数]，群友点击按钮抢，随机分配。

支持统一奖励写法：
  /红包 200 5              → 纯金币红包（随机拆分）
  /红包 100金币+电影票 5   → 金币红包，每份附带「电影票」（线下兑现）
  /红包 一箱可乐 3         → 纯自定义红包，每份都是「一箱可乐」
"""

import random
import secrets

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db
import economy

MAX_PACKETS = 30

# token -> {
#   "shares": [int|None], "custom": str, "gold_total": int,
#   "grabs": {uid: (name, gold_amount, custom)}, "sender": str,
# }
REDPACKETS = {}


def _describe(amount, custom):
    """把 (金币, 自定义) 组合成一句奖励文案。"""
    parts = []
    if amount:
        parts.append(f"{amount} 金币")
    if custom:
        parts.append(custom)
    return " + ".join(parts) if parts else "空气一份 😶"


async def cmd_redpacket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/红包 奖励 [份数]  —— 例如 /红包 200 5、/红包 100金币+电影票 5、/红包 一箱可乐 3"""
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("红包只能在群里发哦～")
        return
    if not context.args:
        await update.message.reply_text(
            "用法：/红包 奖励 [份数]（默认 5 份，最多 30 份）\n"
            "　/红包 200 5              ← 200 金币分 5 份随机抢\n"
            "　/红包 100金币+电影票 5   ← 每份 = 随机金币 + 电影票\n"
            "　/红包 一箱可乐 3         ← 纯自定义，3 份都是可乐"
        )
        return

    total_raw = context.args[0]
    n = int(context.args[1]) if len(context.args) > 1 and context.args[1].isdigit() else 5
    n = max(1, min(n, MAX_PACKETS))

    gold, custom = economy.parse_reward(total_raw)
    # 兼容旧写法「/红包 200」不带"金币"两字
    if gold is None and not custom and total_raw.isdigit():
        gold = int(total_raw)
    if gold is None and not custom:
        await update.message.reply_text(
            "奖励写法没看懂…像这样：/红包 200 5、/红包 100金币+电影票 5、/红包 一箱可乐 3"
        )
        return

    if gold is not None:
        gold_total = max(n, min(gold, 100000))  # 每份至少 1 金币
        shares = _split(gold_total, n)
        row = db.ensure_user(update.effective_user.id)
        if row["points"] < gold_total:
            await update.message.reply_text(
                f"💰 余额不足：要发 {gold_total} 金币的红包，你只有 {row['points']}。先去 /签到 赚钱吧～"
            )
            return
        db.add_points(update.effective_user.id, -gold_total)
        total_line = f"💰 金币 {gold_total} ／ {n} 份" + (f" ／ 每份附赠 {custom}" if custom else "")
    else:
        gold_total = 0
        shares = [None] * n  # 纯自定义红包：每份都是同一文案
        total_line = f"🎁 每份：{custom} ／ {n} 份"

    token = secrets.token_hex(4)
    REDPACKETS[token] = {
        "shares": shares,
        "custom": custom or "",
        "gold_total": gold_total,
        "grabs": {},
        "sender": update.effective_user.first_name or update.effective_user.username or str(update.effective_user.id),
    }

    text = (
        f"🧧 {update.effective_user.first_name} 发了一个红包！\n"
        f"{total_line}\n"
        f"剩余 {n} 份待抢"
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🧧 开抢", callback_data=f"grab:{token}")]]
    )
    msg = await update.message.reply_text(text, reply_markup=keyboard)
    REDPACKETS[token]["msg_id"] = msg.message_id


def _split(total: int, n: int):
    """把 total 拆成 n 份随机正整数（二倍均值法）。"""
    shares = []
    remaining = total
    for i in range(n - 1):
        avg = remaining / (n - i)
        take = max(1, min(remaining - (n - i - 1), int(random.uniform(0.1, 1.9) * avg)))
        shares.append(take)
        remaining -= take
    shares.append(remaining)
    random.shuffle(shares)
    return shares


async def cb_grab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not db.is_chat_authorized(query.message.chat_id):
        await query.answer("本群未获得使用授权", show_alert=True)
        return
    token = query.data.split(":", 1)[1]
    rp = REDPACKETS.get(token)
    if not rp:
        await query.answer("红包已被抢完或已过期", show_alert=True)
        return

    user = query.from_user
    if user.id in rp["grabs"]:
        await query.answer("你已经抢过了，每人限一次～")
        return
    if not rp["shares"]:
        await query.answer("手慢了，红包抢完啦😭", show_alert=True)
        return

    amount = rp["shares"].pop()
    custom = rp["custom"]
    name = user.first_name or user.username or str(user.id)
    rp["grabs"][user.id] = (name, amount or 0, custom)

    if amount:
        db.add_points(user.id, amount)
    await query.answer(f"🎉 抢到 {_describe(amount, custom)}！")

    if rp["shares"]:
        try:
            await query.edit_message_text(
                f"🧧 {rp['sender']} 的红包已被抢……\n"
                f"剩余 {len(rp['shares'])} 份 ／ {len(rp['grabs'])} 人已入账",
                reply_markup=query.message.reply_markup,
            )
        except Exception:
            pass
    else:
        # 抢完：最终战况（金币排手气，纯自定义按抢的顺序）
        if rp["gold_total"]:
            ordered = sorted(rp["grabs"].items(), key=lambda kv: kv[1][1], reverse=True)
            others_note = ""
        else:
            ordered = list(rp["grabs"].items())
            others_note = "\n（纯自定义奖励，请各自找发起者领取）"
        best_id = ordered[0][0] if rp["gold_total"] else None
        lines = [f"🧧 {rp['sender']} 的红包已被抢完！", "", "📊 战况："]
        for uid, (name, amount, custom) in ordered:
            crown = "👑" if rp["gold_total"] and uid == best_id else "　"
            lines.append(f"{crown} {_describe(amount, custom)} ｜ {name}")
        lines.append(others_note)
        try:
            await query.edit_message_text("\n".join(lines))
        except Exception:
            pass
        REDPACKETS.pop(token, None)
