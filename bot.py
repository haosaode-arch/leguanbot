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
import jielong
import lottery
import redpacket
import web

logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_NAME = "🎰 娱乐机器人"

HELP_TEXT = (
    f"👋 我是 {BOT_NAME}！功能菜单：\n\n"
    "💰 经济\n"
    "　/签到 —— 每日签到领金币（连续签到有加成）\n"
    "　/余额 —— 查看我的钱包和战绩\n"
    "　/排行 —— 金币排行榜\n\n"
    "🎁 群互动\n"
    "　/抽奖 奖品 [分钟] —— 发起定时抽奖，按钮报名\n"
    "　/轮盘 奖品 [人数] —— 俄罗斯轮盘，人满开枪淘汰\n"
    "　/红包 总额 [份数] —— 手气红包，点按钮开抢\n"
    "　/点人 问题 —— 随机 @ 一个最近活跃的群友\n\n"
    "🎲 小游戏\n"
    "　/骰子 [数量] —— 掷六面骰\n"
    "　/硬币 —— 抛硬币\n"
    "　/猜拳 石头｜剪刀｜布 —— 与机器人猜拳赢金币\n\n"
    "🧩 接龙\n"
    "　/接龙 词语 —— 开局或接词\n"
    "　/接龙 —— 查看进度\n"
    "　/接龙 结束 —— （开局者/管理员）结束\n\n"
    "中文用法：/签到 /骰子 3 /抽奖 一等奖 5 · 英文用法：/signin /lottery"
)

# 中文命令 → 处理函数。消息形如「/骰子 3」，按最长前缀匹配。
CHINESE_COMMANDS = {
    "签到": economy.cmd_signin,
    "余额": economy.cmd_balance,
    "排行": economy.cmd_top,
    "骰子": fun.cmd_dice,
    "硬币": fun.cmd_coin,
    "猜拳": fun.cmd_rps,
    "点人": fun.cmd_pick,
    "抽奖": lottery.cmd_lottery,
    "轮盘": lottery.cmd_roulette,
    "红包": redpacket.cmd_redpacket,
    "接龙": jielong.cmd_chain,
    "帮助": None,  # 在下方 handler 内指向 cmd_help
}


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)


async def chinese_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """把「/骰子 3」「/红包200」这类中文 slash 命令转发到对应 handler。"""
    text = update.message.text or ""
    if not text.startswith("/"):
        return
    body = text[1:]
    # 命令词长度 1 或 2（本表均为 2 字命令）
    for length in (2, 1):
        head = body[:length]
        if head in CHINESE_COMMANDS or (head == "帮助" and length == 2):
            rest = body[length:].lstrip()
            if rest.startswith("@"):  # 忽略 /cmd@botname 形式
                return
            context.args = rest.split()
            handler = cmd_help if head == "帮助" else CHINESE_COMMANDS[head]
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

    # 0 组：旁路记录活跃用户（不拦截消息）
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_activity), group=-1)
    # 所有消息（含命令）也用于记录，保证发命令的人也可能被点到
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

    # 中文命令
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^/"), chinese_command))

    # 按钮回调
    app.add_handler(CallbackQueryHandler(lottery.cb_lot_join, pattern="^lotjoin$"))
    app.add_handler(CallbackQueryHandler(lottery.cb_rou_join, pattern="^roujoin$"))
    app.add_handler(CallbackQueryHandler(redpacket.cb_grab, pattern="^grab:"))

    app.add_error_handler(on_error)

    print(f"🤖 {BOT_NAME} 启动成功，监听更新中…… Ctrl+C 退出。")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
