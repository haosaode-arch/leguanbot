# -*- coding: utf-8 -*-
"""经济系统：每日签到、余额、排行榜。"""

import datetime
import random

from telegram import Update
from telegram.ext import ContextTypes

import database as db

# 签到奖励：基础 + 连续签到每天递增，第 7 天封顶
BASE_REWARD = 50
STREAK_BONUS = 10
MAX_BONUS = 60


def _today_str() -> str:
    return datetime.date.today().isoformat()


def _yesterday_str() -> str:
    return (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


async def cmd_signin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = db.ensure_user(user.id)

    today = _today_str()
    if row["last_signin"] == today:
        await update.message.reply_text(
            f"📅 {user.first_name} 今天已经签到过啦，明天再来～\n"
            f"💰 当前金币：{row['points']}"
        )
        return

    # 连续签到判断
    if row["last_signin"] == _yesterday_str():
        streak = row["streak"] + 1
    else:
        streak = 1

    bonus = min(STREAK_BONUS * (streak - 1), MAX_BONUS)
    reward = BASE_REWARD + bonus + random.randint(0, 20)

    db.update_user(
        user.id,
        username=user.username,
        first_name=user.first_name,
        last_signin=today,
        streak=streak,
    )
    db.add_points(user.id, reward)
    new_row = db.ensure_user(user.id)

    text = (
        f"✅ {user.first_name} 签到成功！\n"
        f"💵 获得 {reward} 金币（基础 {BASE_REWARD}"
        + (f" + 连签加成 {bonus}" if bonus else "")
        + " + 彩蛋)\n"
        f"🔥 连续签到 {streak} 天\n"
        f"💰 当前金币：{new_row['points']}"
    )
    await update.message.reply_text(text)


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    row = db.ensure_user(user.id)
    db.update_user(user.id, username=user.username, first_name=user.first_name)
    await update.message.reply_text(
        f"💰 {user.first_name} 的钱包\n"
        f"金币：{row['points']}\n"
        f"📊 猜拳战绩：{row['wins']} 胜 {row['losses']} 负\n"
        f"🔥 连签：{row['streak']} 天 ｜ 累计签到：{row['signin_count']} 次"
    )


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = db.top_rich(10)
    if not rows:
        await update.message.reply_text("榜上还没有人，快去 /签到 赚金币吧！")
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 金币排行榜"]
    for i, r in enumerate(rows):
        name = r["first_name"] or (r["username"] and f"@{r['username']}") or "神秘人"
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} {name} — {r['points']} 金币")
    await update.message.reply_text("\n".join(lines))
