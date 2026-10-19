# -*- coding: utf-8 -*-
"""答题游戏

管理员私聊 /出题 题目|标准答案|奖励(可选)  →  到群里 /发题 发布  →
群友私聊机器人发答案，第一名答对即拿奖：
- 奖励写「N金币」自动入账
- 其他文案为自定义奖励，由管理员线下兑现

默认奖励用私聊 /答题奖励 200金币 设置；每题可在出题时单独覆盖。
错误答案累计达 MAX_WRONG 时，群里自动公布答案并结束本题。
"""

import html
import re

from telegram import Update
from telegram.ext import ContextTypes

import database as db
import economy

MAX_WRONG = 20
PENDING = {}   # admin_id -> 暂存题 {question, answer, reward_text, gold}
ACTIVE = {}    # chat_id  -> 进行中题 {question, answer, reward_text, gold, creator, wrong}


def _norm(text: str) -> str:
    """答案归一化：去掉标点空白，转小写再比对。"""
    return re.sub(r"[^\w]", "", text, flags=re.UNICODE).lower()


def parse_reward(text: str, fallback: str):
    """带默认值的奖励解析（走 economy.parse_reward 统一口径）。"""
    text = (text or "").strip() or fallback
    gold, custom = economy.parse_reward(text)
    return gold, custom


def reward_display(gold, custom):
    parts = []
    if gold:
        parts.append(f"{gold} 金币")
    if custom:
        parts.append(custom)
    return " + ".join(parts) if parts else "无"


async def _is_admin(user, chat_id, context) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def _finish(chat_id, bot, winner=None):
    """结束本题并在群里播报；winner 为 mention_html() 或 None（无人答对→公布答案）。"""
    state = ACTIVE.pop(chat_id, None)
    if not state:
        return
    if winner:
        text = (
            "🏁 答题结束：有人答对啦！\n"
            f"🏆 {winner} 抢先答对——「{html.escape(state['answer'])}」\n"
            f"🎁 获得：{html.escape(state['reward_text'])}"
        )
    else:
        text = (
            "🏁 答题结束：累计错误答案太多，无人猜中。\n"
            f"❓ 答案公布：<b>{html.escape(state['answer'])}</b>"
        )
    try:
        bot.send_message(chat_id, text, parse_mode="HTML")
    except Exception:
        pass


# ---------------- 默认奖励设置（私聊） ----------------

async def cmd_set_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("为避免刷屏，请私聊我设置奖励哦～")
        return

    text = " ".join(context.args or []).strip()
    if not text:
        cur = db.get_setting("quiz_reward") or "100金币"
        await update.message.reply_text(
            "🎯 当前默认奖励：" + cur + "\n\n"
            "设置方法（私聊）：\n"
            "　/答题奖励 200金币          ← 金币奖，答对自动入账\n"
            "　/答题奖励 100金币+奶茶 🧋  ← 金币 + 自定义兑现\n"
            "　/答题奖励 一杯奶茶 🧋      ← 纯自定义奖励，答对后由管理员线下兑现"
        )
        return

    gold, custom = parse_reward(text, "100金币")
    stored = reward_display(gold, custom)
    db.set_setting("quiz_reward", stored)
    await update.message.reply_text(f"✅ 默认奖励已更新为：{stored}")


# ---------------- 出题（私聊创建，防答案泄露） ----------------

async def cmd_create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "⚠️ 请私聊我出题！在群里发出题命令会把标准答案一起暴露。\n"
            "私聊发：/出题 题目|标准答案|奖励(可选)\n"
            "创建成功后，到目标群发 /发题 即可发布。"
        )
        return

    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "用法：/出题 题目|标准答案|奖励(可选)\n"
            "　例：/出题 世界上最小的岛国是哪一个？|马尔代夫|50金币\n"
            "　例：/出题 我最爱喝的奶茶是什么？|珍珠奶茶|一杯奶茶\n"
            "不填奖励时使用 /答题奖励 里设置的默认值。\n"
            "创建后到目标群发 /发题；随时可用 /撤销出题 撤销。"
        )
        return

    parts = " ".join(context.args).split("|")
    if len(parts) < 2 or not parts[0].strip() or not parts[1].strip():
        await update.message.reply_text(
            "格式不对：/出题 题目|标准答案|奖励(可选)\n"
            "题目和答案必需，用竖线 | 分隔。"
        )
        return

    question, answer = parts[0].strip(), parts[1].strip()
    reward_raw = parts[2].strip() if len(parts) >= 3 else ""
    gold, custom = parse_reward(reward_raw, db.get_setting("quiz_reward") or "100金币")
    reward_text = reward_display(gold, custom)

    PENDING[uid] = {
        "question": question, "answer": answer,
        "gold": gold, "custom": custom, "reward_text": reward_text,
    }
    await update.message.reply_text(
        "✅ 题目已暂存（未公布）：\n"
        f"❓ {question}\n"
        f"🔑 标准答案：{answer}\n"
        f"🎁 奖励：{reward_text}\n\n"
        "下一步：到目标群发送 /发题 即可发布。"
    )


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        await update.message.reply_text("撤销出题请私聊我操作～")
        return
    if PENDING.pop(update.effective_user.id, None):
        await update.message.reply_text("✅ 已撤销暂存的题目。")
    else:
        await update.message.reply_text("你目前没有暂存的题目。")


# ---------------- 发布（群内，仅管理员） ----------------

async def cmd_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("发题请在目标群里操作：进入群聊发 /发题。")
        return
    user = update.effective_user
    if not await _is_admin(user, chat.id, context):
        await update.message.reply_text("只有群管理员能发题。")
        return

    state = PENDING.pop(user.id, None)
    if not state:
        await update.message.reply_text("你还没有暂存的题目，请先私聊我：/出题 题目|标准答案|奖励")
        return
    if chat.id in ACTIVE:
        PENDING[user.id] = state  # 归还暂存
        await update.message.reply_text("本群已有一道进行中的题目，请等它结束后再发～")
        return

    ACTIVE[chat.id] = {
        "question": state["question"],
        "answer": state["answer"],
        "reward_text": state["reward_text"],
        "gold": state["gold"],
        "custom": state.get("custom", ""),
        "creator": user.id,
        "wrong": 0,
    }
    await update.message.reply_text(
        "🎯 答题开始！\n\n"
        f"❓ {state['question']}\n"
        f"🎁 奖励：{state['reward_text']}\n\n"
        "✉️ 快私聊我发送你的答案，第一个答对的人拿奖！"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/答题 —— 查看本群当前答题进度。"""
    chat = update.effective_chat
    state = ACTIVE.get(chat.id)
    if not state:
        await update.message.reply_text("本群当前没有进行中的答题。管理员可私聊我 /出题 创建～")
        return
    await update.message.reply_text(
        f"🎯 进行中：{state['question']}\n"
        f"🎁 奖励：{state['reward_text']}\n"
        f"❌ 已收到 {state['wrong']} 个错误答案"
    )


# ---------------- 私聊判题 ----------------

async def cb_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return
    if not db.is_game_enabled("quiz"):  # Web 端关闭答题游戏 → 私聊判题也停
        return
    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    if not text or not ACTIVE:
        return
    norm = _norm(text)

    hit = None          # 命中的 chat_id
    attempted = False   # 是否至少对一道"自己参与"的题进行过作答

    for chat_id in list(ACTIVE.keys()):
        state = ACTIVE[chat_id]
        if uid == state["creator"]:
            await update.message.reply_text("你是出题人，不能自己作答哦 😄")
            continue
        try:
            member = await context.bot.get_chat_member(chat_id, uid)
            if member.status == "left":
                continue  # 不在这个群，与其答题无关
        except Exception:
            continue
        attempted = True

        if _norm(state["answer"]) == norm:
            hit = chat_id
            break

        state["wrong"] += 1
        if state["wrong"] >= MAX_WRONG:
            _finish(chat_id, context.bot)  # 无人答对 → 公布答案

    if hit is not None:
        state = ACTIVE.get(hit)
        if state:  # re-check：公布逻辑可能刚好把该题关掉
            if state["gold"] is not None:
                db.add_points(uid, state["gold"])
            got_text = reward_display(state["gold"], state["custom"])
            suffix = "\n记得找管理员线下领取哦 🧋" if state["custom"] else ""
            await update.message.reply_text(
                f"🎉 正确！答案就是「{state['answer']}」\n奖励：{got_text}{suffix}"
            )
            _finish(hit, context.bot, winner=update.effective_user.mention_html())
    elif attempted:
        await update.message.reply_text("❌ 不对，再想想～")
