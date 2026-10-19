# -*- coding: utf-8 -*-
"""TG 娱乐机器人主入口。

Token 读取顺序：环境变量 BOT_TOKEN → 同目录 token.txt。
运行：python bot.py
"""

import logging
import os
import sys
import threading
import urllib.parse

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import database as db
import economy
import fun
import guessnum
import jielong
import lottery
import math24
import quiz
import redpacket
import duel
import web

logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_NAME = "🎰 娱乐机器人"

# ---------------- 游戏独立开关 ----------------

GAME_NAMES = db.GAME_NAMES  # key -> 中文名


def gated(game: str, handler):
    """命令闸门：若该游戏在 Web 端被关闭，回复提示并拦截。"""
    name = GAME_NAMES.get(game, game)

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not db.is_game_enabled(game):
            await update.message.reply_text(
                f"⛔「{name}」目前已被管理员临时关闭，请稍后再试～"
            )
            return
        await handler(update, context)

    return wrapper


def build_help_text() -> str:
    mark = lambda g: "（已关闭⛔）" if not db.is_game_enabled(g) else ""
    return (
        f"👋 我是 {BOT_NAME}！功能菜单：\n\n"
        "💰 经济\n"
        f"　/签到 —— 每日签到领金币（连续签到有加成）{mark('signin')}\n"
        "　/余额 —— 查看我的钱包和战绩\n"
        f"　/排行 —— 金币排行榜{mark('top')}\n\n"
        "🎁 群互动\n"
        f"　/抽奖 奖品 [分钟] —— 发起定时抽奖，按钮报名{mark('lottery')}\n"
        f"　/轮盘 奖品 [人数] —— 俄罗斯轮盘，人满开枪淘汰{mark('roulette')}\n"
        f"　/红包 总额 [份数] —— 手气红包，点按钮开抢{mark('redpacket')}\n"
        f"　/点人 问题 —— 随机 @ 一个最近活跃的群友{mark('pick')}\n\n"
        "🎲 小游戏\n"
        f"　/骰子 [数量] —— 掷六面骰{mark('dice')}\n"
        f"　/硬币 —— 抛硬币{mark('coin')}\n"
        f"　/猜拳 石头｜剪刀｜布 —— 与机器人猜拳赢金币{mark('rps')}\n\n"
        "🧩 接龙\n"
        f"　/接龙 词语 —— 开局或接词{mark('jielong')}\n"
        "　/接龙 —— 查看进度\n"
        "　/接龙 结束 —— （开局者/管理员）结束\n\n"
        "🎯 答题\n"
        f"　/出题 题目｜标准答案｜奖励 — （私聊）管理员出题{mark('quiz')}\n"
        "　/发题 —— （群里）发布暂存的题目\n"
        "　/答案请私聊发送给机器人 —— 第一答对拿奖\n\n"
        "🧮 更多游戏\n"
        f"　/24点 [算式] —— 四个数凑出 24，答对 +40 金币（每人每天 5 次）{mark('math24')}\n"
        f"　/决斗 [押注] —— 回复某人约战掷骰，赢家通吃{mark('duel')}\n"
        f"　/猜数字 [数字] —— 猜 1~999，范围自动收窄（每人每天 3 次）{mark('guessnum')}\n\n"
        "中文用法：/签到 /骰子 3 /抽奖 一等奖 5 · 英文用法：/signin /lottery"
    )


# 中文命令 → 处理函数（闸门按 key 拦截）。消息形如「/骰子 3」，按最长前缀匹配。
CHINESE_COMMANDS = {
    "签到": gated("signin", economy.cmd_signin),
    "余额": economy.cmd_balance,   # 余额始终可查
    "排行": gated("top", economy.cmd_top),
    "骰子": gated("dice", fun.cmd_dice),
    "硬币": gated("coin", fun.cmd_coin),
    "猜拳": gated("rps", fun.cmd_rps),
    "点人": gated("pick", fun.cmd_pick),
    "抽奖": gated("lottery", lottery.cmd_lottery),
    "轮盘": gated("roulette", lottery.cmd_roulette),
    "红包": gated("redpacket", redpacket.cmd_redpacket),
    "接龙": gated("jielong", jielong.cmd_chain),
    "答题": gated("quiz", quiz.cmd_stats),
    "出题": gated("quiz", quiz.cmd_create),
    "发题": gated("quiz", quiz.cmd_publish),
    "答题奖励": gated("quiz", quiz.cmd_set_reward),
    "撤销出题": gated("quiz", quiz.cmd_cancel),
    "24点": gated("math24", math24.cmd),
    "决斗": gated("duel", duel.cmd_duel),
    "猜数字": gated("guessnum", guessnum.cmd),
    "猜": gated("guessnum", guessnum.cmd),
    "帮助": None,  # 在下方 handler 内指向 cmd_help
}


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(build_help_text())


async def chinese_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """把「/骰子 3」「/红包200」「/答题奖励 100金币」这类中文 slash 命令转发到对应 handler。"""
    text = update.message.text or ""
    if not text.startswith("/"):
        return
    body = text[1:]
    # 命令词按最长前缀匹配（命令长度 2~4 字不等）
    for length in sorted({len(k) for k in CHINESE_COMMANDS}, reverse=True):
        head = body[:length]
        if head == "帮助" and length == 2:
            rest = body[length:].lstrip()
            if rest.startswith("@"):  # 忽略 /cmd@botname 形式
                return
            context.args = rest.split()
            await cmd_help(update, context)
            return
        handler = CHINESE_COMMANDS.get(head)
        if handler is not None:
            rest = body[length:].lstrip()
            if rest.startswith("@"):  # 忽略 /cmd@botname 形式
                return
            context.args = rest.split()
            await handler(update, context)
            return
    # 未识别的中文命令 → 静默忽略


async def track_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """记录各群最近 10 分钟发过言的用户，供「/点人」使用。"""
    fun.record_activity(update)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error("处理更新时出错：", exc_info=context.error)


def get_proxy_url():
    """代理优先级：Web 控制台保存的设置 > 环境变量 PROXY_URL > 不设代理。"""
    if db.get_setting("proxy_enabled") == "1":
        ptype = db.get_setting("proxy_type") or "socks5"
        host = db.get_setting("proxy_host") or ""
        port = db.get_setting("proxy_port") or ""
        user = urllib.parse.quote(db.get_setting("proxy_user") or "")
        pw = urllib.parse.quote(db.get_setting("proxy_pass") or "")
        if host and port:
            auth = f"{user}:{pw}@" if user else ""
            return f"{ptype}://{auth}{host}:{port}"
    return os.environ.get("PROXY_URL") or None


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")
        if os.path.exists(token_file):
            with open(token_file, "r", encoding="utf-8-sig") as f:
                token = f.read().strip()
    if not token:
        print("❌ 未找到机器人 token！\n"
              "请把从 @BotFather 拿到的 token 存到同目录 token.txt，"
              "或设置环境变量 BOT_TOKEN 后重试。")
        sys.exit(1)

    db.init_db()
    web.init()

    # 启动 Web 控制台（WEB_PORT=0 可关闭）
    web_port = int(os.environ.get("WEB_PORT", "8080"))
    if web_port > 0:
        threading.Thread(target=web.start, args=(web_port,), daemon=True, name="web").start()
        print(f"🖥  Web 控制台已启动: http://0.0.0.0:{web_port}（默认账号 leguan）")

    # 应用代理设置（Web 控制台 > 环境变量）
    proxy_url = get_proxy_url()
    if proxy_url:
        safe = proxy_url.replace("//" + proxy_url.split("//", 1)[1].split("@", 1)[0] + "@", "//***:***@") if "@" in proxy_url else proxy_url
        print(f"🌐 使用代理连接 Telegram: {safe}")
        builder = Application.builder().token(token)
        try:
            builder = builder.proxy_url(proxy_url).get_updates_proxy_url(proxy_url)
        except AttributeError:  # 兼容老版本 PTB
            builder = builder.proxy_url(proxy_url)
        app = builder.build()
    else:
        app = Application.builder().token(token).build()

    # 0 组：旁路记录活跃用户（不拦截消息）；命令消息也记录，保证发命令的人也可能被点到
    app.add_handler(MessageHandler(filters.TEXT, track_activity), group=-1)

    # 英文命令
    app.add_handler(CommandHandler(["signin"], economy.cmd_signin))
    app.add_handler(CommandHandler(["balance"], economy.cmd_balance))
    app.add_handler(CommandHandler(["top"], economy.cmd_top))
    app.add_handler(CommandHandler(["dice"], fun.cmd_dice))
    app.add_handler(CommandHandler(["coin"], fun.cmd_coin))
    app.add_handler(CommandHandler(["rps"], fun.cmd_rps))
    app.add_handler(CommandHandler(["pick"], fun.cmd_pick))
    app.add_handler(CommandHandler(["lottery"], lottery.cmd_lottery))
    app.add_handler(CommandHandler(["roulette"], lottery.cmd_roulette))
    app.add_handler(CommandHandler(["redpacket"], redpacket.cmd_redpacket))
    app.add_handler(CommandHandler(["chain"], jielong.cmd_chain))
    app.add_handler(CommandHandler(["help"], cmd_help))

    # 答题
    app.add_handler(CommandHandler(["quiz"], gated("quiz", quiz.cmd_stats)))
    app.add_handler(CommandHandler(["ask"], gated("quiz", quiz.cmd_create)))
    app.add_handler(CommandHandler(["publish"], gated("quiz", quiz.cmd_publish)))
    app.add_handler(CommandHandler(["quizreward"], gated("quiz", quiz.cmd_set_reward)))
    app.add_handler(CommandHandler(["quizcancel"], gated("quiz", quiz.cmd_cancel)))
    app.add_handler(CommandHandler(["math24"], gated("math24", math24.cmd)))
    app.add_handler(CommandHandler(["duel"], gated("duel", duel.cmd_duel)))
    app.add_handler(CommandHandler(["guess"], gated("guessnum", guessnum.cmd)))

    # 中文命令
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^/"), chinese_command))

    # 按钮回调
    app.add_handler(CallbackQueryHandler(lottery.cb_lot_join, pattern="^lotjoin$"))
    app.add_handler(CallbackQueryHandler(lottery.cb_rou_join, pattern="^roujoin$"))
    app.add_handler(CallbackQueryHandler(redpacket.cb_grab, pattern="^grab:"))
    app.add_handler(CallbackQueryHandler(duel.cb_accept, pattern="^duelok:"))

    # 私聊纯文本 → 答题判题（需要命令之外独立处理）
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, quiz.cb_answer)
    )

    app.add_error_handler(on_error)

    print(f"🤖 {BOT_NAME} 启动成功，监听更新中…… Ctrl+C 退出。")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
