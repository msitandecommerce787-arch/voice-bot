import aiosqlite
import os
from datetime import datetime, timedelta

DB_PATH = "bot.db"

PLANS = {
    "basic":   {"price_bdt": 100,  "price_usdt": 1,  "voice_limit": 5,   "days": 30, "label": "🥉 Basic — 5 voice"},
    "pro":     {"price_bdt": 200,  "price_usdt": 2,  "voice_limit": 10,  "days": 30, "label": "🥈 Pro — 10 voice"},
    "elite":   {"price_bdt": 300,  "price_usdt": 3,  "voice_limit": 15,  "days": 30, "label": "🥇 Elite — 15 voice"},
    "gold":    {"price_bdt": 400,  "price_usdt": 4,  "voice_limit": 20,  "days": 30, "label": "💎 Gold — 20 voice"},
    "premium": {"price_bdt": 500,  "price_usdt": 5,  "voice_limit": 25,  "days": 30, "label": "👑 Premium — 25 voice"},
    "ultra":   {"price_bdt": 1000, "price_usdt": 10, "voice_limit": 50,  "days": 30, "label": "🔥 Ultra — 50 voice"},
    "mega":    {"price_bdt": 2000, "price_usdt": 20, "voice_limit": 100, "days": 30, "label": "💠 Mega — 100 voice"},
    "max":     {"price_bdt": 4000, "price_usdt": 40, "voice_limit": 200, "days": 30, "label": "🚀 Max — 200 voice"},
}


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                joined_at TEXT DEFAULT (datetime('now')),
                is_banned INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                plan TEXT,
                voice_limit INTEGER,
                voices_used INTEGER DEFAULT 0,
                started_at TEXT,
                expires_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                method TEXT,
                amount REAL,
                plan TEXT,
                trx_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now')),
                verified_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS voice_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                text_length INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        await db.commit()


async def upsert_user(user_id, username, full_name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, full_name=excluded.full_name
        """, (user_id, username or "", full_name or ""))
        await db.commit()


async def is_banned(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return bool(row and row["is_banned"])


async def get_active_subscription(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM subscriptions
            WHERE user_id=? AND is_active=1 AND expires_at > datetime('now')
            ORDER BY expires_at DESC LIMIT 1
        """, (user_id,)) as cur:
            return await cur.fetchone()


async def can_use_voice(user_id):
    sub = await get_active_subscription(user_id)
    if not sub:
        return False, "no_sub"
    if sub["voices_used"] >= sub["voice_limit"]:
        return False, "limit_reached"
    return True, "ok"


async def increment_voice_usage(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE subscriptions SET voices_used = voices_used + 1
            WHERE user_id=? AND is_active=1 AND expires_at > datetime('now')
        """, (user_id,))
        await db.commit()


async def create_subscription(user_id, plan):
    plan_data = PLANS[plan]
    expires = (datetime.utcnow() + timedelta(days=plan_data["days"])).isoformat()
    started = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE subscriptions SET is_active=0 WHERE user_id=?", (user_id,))
        await db.execute("""
            INSERT INTO subscriptions (user_id, plan, voice_limit, started_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, plan, plan_data["voice_limit"], started, expires))
        await db.commit()


async def save_payment(user_id, method, amount, plan, trx_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO payments (user_id, method, amount, plan, trx_id)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, method, amount, plan, trx_id))
        await db.commit()


async def approve_payment(trx_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM payments WHERE trx_id=? AND status='pending'", (trx_id,)) as cur:
            payment = await cur.fetchone()
        if not payment:
            return None
        await db.execute("""
            UPDATE payments SET status='verified', verified_at=datetime('now') WHERE trx_id=?
        """, (trx_id,))
        await db.commit()
        return payment


async def log_voice(user_id, text_length):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO voice_logs (user_id, text_length) VALUES (?, ?)", (user_id, text_length))
        await db.commit()


async def get_admin_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        stats = {}
        async with db.execute("SELECT COUNT(*) as c FROM users") as cur:
            stats["total_users"] = (await cur.fetchone())["c"]
        async with db.execute("""
            SELECT COUNT(*) as c FROM subscriptions WHERE is_active=1 AND expires_at > datetime('now')
        """) as cur:
            stats["active_subs"] = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) as c FROM voice_logs") as cur:
            stats["total_voices"] = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) as c FROM payments WHERE status='verified'") as cur:
            stats["total_payments"] = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) as c FROM payments WHERE status='pending'") as cur:
            stats["pending_payments"] = (await cur.fetchone())["c"]
        return stats


async def get_pending_payments():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT p.*, u.username, u.full_name FROM payments p
            LEFT JOIN users u ON p.user_id = u.user_id
            WHERE p.status='pending' ORDER BY p.created_at DESC LIMIT 10
        """) as cur:
            return await cur.fetchall()


async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT u.*, s.plan, s.voices_used, s.voice_limit, s.expires_at
            FROM users u
            LEFT JOIN subscriptions s ON u.user_id = s.user_id AND s.is_active=1
            ORDER BY u.joined_at DESC LIMIT 20
        """) as cur:
            return await cur.fetchall()


async def ban_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))
        await db.commit()


async def unban_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))
        await db.commit()


async def give_free_sub(user_id, plan):
    await create_subscription(user_id, plan)
