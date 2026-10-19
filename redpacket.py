# -*- coding: utf-8 -*-
"""红包：/红包 总金额 [份数]，群友点击按钮抢，随机分配。"""

import random
import secrets

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import database as db

MAX_PACKETS = 30

# 抢红包的防重复：token -> {"total": n, "shares": [int], "grabs": {uid: (name, 领到数)}, "msg_id": int}
REDPACKETS = {}


async def cmd_redpacket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/红包 总金额 [份数]  —— 例如 /红包 200 5"""
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("红包只能在群里发哦～")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text('用法：/红包 总金额 [份数]\n例如：/红包 200 5（默认 5 份）')
        return

    total = int(context.args[0])
    n = int(context.args[1]) if len(context.args) > 1 and context.args[1].isdigit() else 5
    n = max(1, min(n, MAX_PACKETS))
    total = max(n, min(total, 100000))  # 每份至少 1 金币

    user = update.effective_user
    row = db.ensure_user(user.id)
    if row["points"] < total:
        await update.message.reply_text(
            f"💰 余额不足：要发 {total} 金币的红包，你只有 {row['points']}。先去 /签到 赚钱吧～"
        )
        return
    db.add_points(user.id, -total)

    # 贪心随机拆分：份份 >= 1 且和为 total
    shares = _split(total, n)
    token = secrets.token_hex(4)
    REDPACKETS[token] = {
        "total": total,
        "shares": shares,
        "grabs": {},
        "msg_id": None,
        "sender": user.first_name or user.username or str(user.id),
    }

    text = (
        f"🧧 {user.first_name} 发了一个红包！\n"
        f"💵 总额 {total} 金币 ／ {n} 份\n"
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


def _summary_text(token: str):
    rp = REDPACKETS[token]
    lines = [f"🧧 拆分中… 剩余 {len(rp['shares'])} 份"]
    for uid, (name, amount) in list(rp["grabs"].items())[-5:]:
        lines.append(f"　{amount} 金币 ｜ {name}")
    return "\n".join(lines)


async def cb_grab(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    token = query.data.split(":", 1)[1]
    rp = REDPACKETS.get(token)
    if not rp:
        await query.answer("红包已被抢完或已过期", show_alert=True)
        return

    user = query.from_user
    if user.id in rp["grabs"]:
        got = rp["grabs"][user.id][1]
        await query.answer(f"你已抢到 {got} 金币，别贪心～")
        return
    if not rp["shares"]:
        await query.answer("手慢了，红包抢完啦😭", show_alert=True)
        return

    amount = rp["shares"].pop()
    rp["grabs"][user.id] = (user.first_name or user.username or str(user.id), amount)
    db.add_points(user.id, amount)
    await query.answer(f"🎉 抢到 {amount} 金币！")

    if rp["shares"]:
        try:
            await query.edit_message_text(
                f"🧧 {rp['sender']} 的红包已被抢……\n剩余 {len(rp['shares'])} 份\n{len(rp['grabs'])} 人已入账",
                reply_markup=query.message.reply_markup,
            )
        except Exception:
            pass
    else:
        # 抢完了：展示最终战况
        best = sorted(rp["grabs"].items(), key=lambda kv: kv[1][1], reverse=True)[0]
        lines = [f"🧧 {rp['sender']} 的红包已被抢完！", "", "📊 战况："]
        for uid, (name, amount) in sorted(rp["grabs"].items(), key=lambda kv: kv[1][1], reverse=True):
            crown = "👑" if uid == best[0] else "　"
            lines.append(f"{crown} {amount:>4} 金币 ｜ {name}")
        try:
            await query.edit_message_text("\n".join(lines))
        except Exception:
            REDPACKETS.pop(token, None)
            return
        REDPACKETS.pop(token, None)
