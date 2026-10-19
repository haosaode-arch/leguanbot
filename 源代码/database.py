# -*- coding: utf-8 -*-
"""数据库层：用户积分、签到、胜负统计（SQLite，自动建表）。"""

import hashlib
import os
import sqlite3
import threading

# 数据库目录：Docker 里挂卷到 /app/data，本地默认还是脚本目录
DATA_DIR = os.environ.get("DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "bot_data.db")
_lock = threading.Lock()


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
    """加减积分，负数会一直扣到 0（不出现负余额）。"""
    with _lock:
        conn = _connect()
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
