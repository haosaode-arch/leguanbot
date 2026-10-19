# -*- coding: utf-8 -*-
"""数据库层：用户积分、签到、胜负统计（SQLite，自动建表）。"""

import hashlib
import datetime
import os
import re
import sqlite3
import threading

# 数据库目录：Docker 里挂卷到 /app/data，本地默认还是脚本目录
DATA_DIR = os.environ.get("DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "bot_data.db")
_lock = threading.Lock()

CN_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间，与服务器容器时区无关


def today_date_cn():
    """当前北京时间（datetime.date）。换日、连签、每日上限都用它，避免容器 UTC 造成 8 点才换日。"""
    return datetime.datetime.now(CN_TZ).date()


def today_cn() -> str:
    return today_date_cn().isoformat()


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------- 设置表 ----------------

SALT = "tgfun::"


def hash_password(pw: str) -> str:
    return hashlib.sha256((SALT + pw).encode("utf-8")).hexdigest()


def get_setting(key: str):
    with _lock:
        conn = _connect()
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else None


def set_setting(key: str, value: str):
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
        conn.close()


def verify_admin(username: str, password: str) -> bool:
    expected_user = get_setting("admin_user") or "leguan"
    expected_hash = get_setting("admin_pass") or hash_password("leguan123")
    return username == expected_user and hash_password(password or "") == expected_hash


# ---------------- 游戏开关 ----------------

GAME_NAMES = {
    "signin":    "签到",
    "top":       "排行榜",
    "dice":      "骰子",
    "coin":      "抛硬币",
    "rps":       "猜拳",
    "pick":      "随机点人",
    "lottery":   "抽奖",
    "roulette":  "轮盘",
    "redpacket": "红包",
    "jielong":   "接龙",
    "quiz":      "答题",
    "math24":    "24点",
    "duel":      "决斗",
    "guessnum":  "猜数字",
}


def is_game_enabled(game: str) -> bool:
    """未设置过的一律视为开启。"""
    return get_setting(f"game_{game}") != "0"


def set_game_enabled(game: str, enabled: bool):
    if game in GAME_NAMES:
        set_setting(f"game_{game}", "1" if enabled else "0")


def game_states():
    return {k: is_game_enabled(k) for k in GAME_NAMES}


# ---------------- 机器人管理员（Web 端配置 TG ID） ----------------

def get_admin_ids():
    """Web 面板设置的 Telegram 用户 ID 列表。"""
    raw = get_setting("admin_ids") or ""
    return [int(x) for x in re.findall(r"\d+", raw)]


def is_bot_admin(user_id) -> bool:
    return user_id in get_admin_ids()


def set_admin_ids_text(text: str):
    """任意分隔格式都行：'12345, 67890' / 换行 / 空格。"""
    set_setting("admin_ids", ",".join(re.findall(r"\d+", text or "")))


# ---------------- 群聊授权白名单（Web 后台配置） ----------------

def get_auth_chats():
    """授权群聊 ID 列表；列表为空 = 不限制。"""
    raw = get_setting("auth_chats") or ""
    return [int(x) for x in re.findall(r"-?\d+", raw)]


def is_chat_authorized(chat_id) -> bool:
    ids = get_auth_chats()
    return (not ids) or chat_id in ids


def set_auth_chats_text(text: str):
    """群 ID 通常为负数：-100xxxxxxxxxx。逗号/空格/换行分隔均可。"""
    set_setting("auth_chats", ",".join(re.findall(r"-?\d+", text or "")))


# ---------------- 每日获奖次数限制（防无限刷币） ----------------

def daily_wins_count(user_id: int, game: str, day: str) -> int:
    with _lock:
        conn = _connect()
        row = conn.execute(
            "SELECT count FROM daily_wins WHERE user_id=? AND game=? AND day=?",
            (user_id, game, day),
        ).fetchone()
        conn.close()
        return row["count"] if row else 0


def add_daily_win(user_id: int, game: str, day: str):
    with _lock:
        conn = _connect()
        conn.execute(
            "INSERT INTO daily_wins (user_id, game, day, count) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(user_id, game, day) DO UPDATE SET count = count + 1",
            (user_id, game, day),
        )
        conn.commit()
        conn.close()


def init_db():
    with _lock:
        conn = _connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                username      TEXT,
                first_name    TEXT,
                points        INTEGER NOT NULL DEFAULT 0,
                last_signin   TEXT,
                streak        INTEGER NOT NULL DEFAULT 0,
                signin_count  INTEGER NOT NULL DEFAULT 0,
                wins          INTEGER NOT NULL DEFAULT 0,
                losses        INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_wins (
                user_id INTEGER NOT NULL,
                game    TEXT    NOT NULL,
                day     TEXT    NOT NULL,
                count   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, game, day)
            );
            """
        )
        # 种子默认管理员（首次运行时写入，之后不会覆盖用户改过的值）
        if conn.execute(
            "SELECT 1 FROM settings WHERE key = 'admin_pass'"
        ).fetchone() is None:
            conn.executemany(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                [
                    ("admin_user", "leguan"),
                    ("admin_pass", hash_password("leguan123")),
                ],
            )
        conn.commit()
        conn.close()


def ensure_user(user_id: int):
    """确保用户存在，返回该行 dict。"""
    with _lock:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row is None:
            cur.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            conn.commit()
            cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
        data = dict(row)
        conn.close()
        return data


def update_user(user_id: int, **fields):
    """按字段更新用户信息。"""
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _lock:
        conn = _connect()
        conn.execute(f"UPDATE users SET {sets} WHERE user_id = ?", (*fields.values(), user_id))
        conn.commit()
        conn.close()


def add_points(user_id: int, delta: int):
    """加减积分（自动补建用户行，防止中奖者无记录时金币丢失）；负数扣到 0 为止。"""
    with _lock:
        conn = _connect()
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        conn.execute(
            "UPDATE users SET points = MAX(0, points + ?) WHERE user_id = ?",
            (delta, user_id),
        )
        conn.commit()
        conn.close()


def top_rich(limit: int = 10):
    """积分排行榜。"""
    with _lock:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM users ORDER BY points DESC, wins DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def global_stats():
    """全站统计：用户数、金币总量、累计签到、猜拳场次。"""
    with _lock:
        conn = _connect()
        row = conn.execute(
            """
            SELECT
                COUNT(*)                              AS users,
                COALESCE(SUM(points), 0)              AS coins,
                COALESCE(SUM(signin_count), 0)        AS signins,
                COALESCE(SUM(wins + losses), 0)       AS rps_games
            FROM users
            """
        ).fetchone()
        conn.close()
        return dict(row)
