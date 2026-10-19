# -*- coding: utf-8 -*-
"""24 点大挑战

/24点                 —— 出题（或查看当前题）
/24点 3*5+8+1         —— 作答（可 + - × ÷ 和括号，四个数字必须各用一次）
/24点 换              —— 跳过本题出下一题（任何人可换）
/24点 结束            ——（bot 管理员/群管理员）结束本轮

答对 +40 金币；每人每天最多领 5 次奖励，超出后纯娱乐不计奖。
答对后自动进入下一轮。
"""

import ast
import random
import re
import time
from fractions import Fraction

from telegram import Update
from telegram.ext import ContextTypes

import database as db

REWARD = 40
DAILY_CAP = 5

ROUNDS = {}  # chat_id -> {"nums": [4 ints], "starter": uid}
_SWAP_CD = {}  # chat_id -> 上次换题时间（防止刷题捣乱）


def _solvable(nums):
    """递归判可解性（精确分数运算）。"""
    if len(nums) == 1:
        return nums[0] == 24
    for i in range(len(nums)):
        for j in range(i + 1, len(nums)):
            a, b = Fraction(nums[i]), Fraction(nums[j])
            rest = [nums[k] for k in range(len(nums)) if k not in (i, j)]
            cands = [a + b, a - b, b - a, a * b]
            if b:
                cands.append(a / b)
            if a:
                cands.append(b / a)
            for c in cands:
                if _solvable(rest + [c]):
                    return True
    return False


def _new_nums():
    while True:
        nums = [random.randint(1, 13) for _ in range(4)]
        if _solvable(nums):
            return nums


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return Fraction(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand)
    if isinstance(node, ast.BinOp):
        l, r = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return l + r
        if isinstance(node.op, ast.Sub):
            return l - r
        if isinstance(node.op, ast.Mult):
            return l * r
        if isinstance(node.op, ast.Div):
            if r == 0:
                raise ZeroDivisionError
            return l / r
    raise ValueError("非法表达式")


def check(expr: str, nums):
    """校验并求值；返回 True/False（表达式非法直接 False）。"""
    clean = expr.replace("×", "*").replace("÷", "/").replace("x", "*").replace("X", "*")
    clean = clean.replace(" ", "")
    if not clean or len(clean) > 50:
        return False
    if re.search(r"[^\d+\-*/()]", clean):
        return False
    used = [int(t) for t in re.findall(r"\d+", clean)]
    if sorted(used) != sorted(nums):
        return False
    try:
        tree = ast.parse(clean, mode="eval")
        return _eval_node(tree) == 24
    except Exception:
        return False


def _announce(text, ctx, chat_id):
    return ctx.bot.send_message(chat_id, text)


async def cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/24点 [算式|换|结束]"""
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("24 点只能在群里玩哦～")
        return

    user = update.effective_user
    arg = " ".join(context.args or []).strip()
    state = ROUNDS.get(chat.id)

    # ---- 跳过 / 结束 ----
    if arg in ("换", "跳过", "新题"):
        last = _SWAP_CD.get(chat.id, 0.0)
        if time.monotonic() - last < 30:
            await update.message.reply_text("⏳ 换题太频繁啦，30 秒内只能换一次～")
            return
        _SWAP_CD[chat.id] = time.monotonic()
        ROUNDS[chat.id] = {"nums": _new_nums(), "starter": user.id}
        nums = " · ".join(str(n) for n in ROUNDS[chat.id]["nums"])
        await update.message.reply_text(f"🔄 换题！本轮 24 点：{nums}")
        return
    if arg == "结束":
        if state and (db.is_bot_admin(user.id) or await _is_chat_admin(user, chat.id, context)):
            ROUNDS.pop(chat.id, None)
            await update.message.reply_text("🏁 24 点已结束。想再玩就发 /24点")
        else:
            await update.message.reply_text("只有 bot 管理员或群管理员能结束。")
        return

    # ---- 作答 ----
    if arg and state:
        if check(arg, state["nums"]):
            name = html_escape_name(update.effective_user)
            day = db.today_cn()
            won = db.daily_wins_count(user.id, "math24", day)
            if won < DAILY_CAP:
                db.add_points(user.id, REWARD)
                db.add_daily_win(user.id, "math24", day)
                note = f"🎁 +{REWARD} 金币已入账（今日第 {won + 1}/{DAILY_CAP} 次奖励）"
            else:
                note = f"😅 今日 {DAILY_CAP} 次奖励已领完，本轮纯娱乐～"
            # 直接进入下一轮
            new_nums = _new_nums()
            ROUNDS[chat.id] = {"nums": new_nums, "starter": user.id}
            nums_txt = " · ".join(str(n) for n in new_nums)
            await update.message.reply_text(
                f"🎉 {name} 解出来了！\n{note}\n\n🧮 新一轮：{nums_txt}\n继续用 /24点 算式 作答！"
            )
        else:
            await update.message.reply_text(
                "❌ 不成立哦！检查一下：四个数字各用一次、算式合法、结果正好 24。"
            )
        return

    # ---- 出题 / 查看 ----
    if state:
        nums = " · ".join(str(n) for n in state["nums"])
        await update.message.reply_text(f"🧮 当前 24 点：{nums}\n用 /24点 算式 作答，或 /24点 换")
        return

    ROUNDS[chat.id] = {"nums": _new_nums(), "starter": user.id}
    nums = " · ".join(str(n) for n in ROUNDS[chat.id]["nums"])
    await update.message.reply_text(
        f"🧮 24 点大挑战开局！\n本轮数字：{nums}\n"
        "在群里发 /24点 算式 作答，四个数字各用一次，可用 + - × ÷ 和括号，结果 = 24。\n"
        f"每轮答对 +{REWARD} 金币，每人每天最多领 {DAILY_CAP} 次。"
    )


def html_escape_name(user):
    import html
    return html.escape(user.first_name or "群友")


async def _is_chat_admin(user, chat_id, context) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False
