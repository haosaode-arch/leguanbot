# -*- coding: utf-8 -*-
"""成语/词语接龙。规则：新词首字 = 上一个词尾字；词长 >= 2；不重复。"""

from telegram import Update
from telegram.ext import ContextTypes

# chat_id -> {"tail": str, "words": list, "longest": str}
CHAINS = {}


async def cmd_chain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/接龙             查看当前进度
       /接龙 词语        提交或开新局（未开局则用第一个词开局）
       /接龙 结束        （发起者或管理员）结束本局"""
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("接龙只能在群里玩哦～")
        return

    user = update.effective_user
    state = CHAINS.get(chat.id)

    text_arg = "".join(context.args or []).strip()

    # --- 结束 ---
    if text_arg in ("结束", "重开"):
        if state and (user.id == state.get("starter") or _is_admin(user, chat.id, context)):
            CHAINS.pop(chat.id, None)
            await update.message.reply_text(
                f"🏁 接龙结束！本轮共接了 {len(state['words'])} 个词，"
                f"最长的一个：{state['longest']}"
            )
        elif state:
            await update.message.reply_text("只有开局的人或管理员能结束接龙～")
        else:
            await update.message.reply_text("当前没有进行中的接龙。用  /接龙 词语  开一局吧！")
        return

    # --- 提交词语 ---
    if not text_arg:
        if state:
            chain_preview = " → ".join(state["words"][-6:])
            await update.message.reply_text(
                "🔗 当前接龙：\n"
                f"{chain_preview}\n"
                f"请接以「{state['tail']}」开头的词：/接龙 XX"
            )
        else:
            await update.message.reply_text("用法：/接龙 词语 —— 第一个词由你开局！")
        return

    word = text_arg

    # --- 开新局 ---
    if not state:
        if len(word) < 2:
            await update.message.reply_text("词至少要有 2 个字哦。")
            return
        CHAINS[chat.id] = {
            "tail": word[-1],
            "words": [word],
            "longest": word,
            "starter": user.id,
        }
        await update.message.reply_text(
            f"🔗 接龙开局！\n起点：{word}\n请下一位接以「{word[-1]}」开头的词"
        )
        return

    # --- 验证 ---
    if word in state["words"]:
        await update.message.reply_text(f"❌「{word}」已经接过了，换一个～")
        return
    if len(word) < 2:
        await update.message.reply_text("词至少要有 2 个字哦。")
        return
    if not word.startswith(state["tail"]):
        await update.message.reply_text(
            f"❌ 要接「{state['tail']}」开头的词，你发的「{word}」接不上。"
        )
        return

    state["words"].append(word)
    state["tail"] = word[-1]
    if len(word) > len(state["longest"]):
        state["longest"] = word

    await update.message.reply_text(
        f"✅ {user.first_name} 接上了「{word}」\n"
        f"🔗 共 {len(state['words'])} 个词，请接「{state['tail']}」开头的！"
    )


async def _is_admin(user, chat_id, context) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False
