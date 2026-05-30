import os
import asyncpg
from datetime import datetime, timedelta

DATABASE_URL = os.environ.get("DATABASE_URL", "")

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

BADGES = {
    "newcomer": {"label": "🌱 Newcomer", "voices": 0},
    "starter":  {"label": "⭐ Starter",  "voices": 10},
    "regular":  {"label": "🔥 Regular",  "voices": 50},
    "pro":      {"label": "💎 Pro",      "voices": 100},
    "legend":   {"label": "👑 Legend",   "voices": 500},
}

_pool = None

async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    return _pool

async def init_db():
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY, username TEXT, full_name TEXT,
            joined_at TIMESTAMP DEFAULT NOW(), is_banned INTEGER DEFAULT 0,
            referral_code TEXT, referred_by BIGINT, reseller_code TEXT,
            reseller_commission INTEGER DEFAULT 0, birthday TEXT)""")
        await c.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY, user_id BIGINT, plan TEXT, voice_limit INTEGER,
            voices_used INTEGER DEFAULT 0, started_at TIMESTAMP, expires_at TIMESTAMP,
            is_active INTEGER DEFAULT 1, gifted_by BIGINT DEFAULT NULL)""")
        await c.execute("""CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY, user_id BIGINT, method TEXT, amount REAL, plan TEXT,
            trx_id TEXT UNIQUE, status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW(), verified_at TIMESTAMP)""")
        await c.execute("""CREATE TABLE IF NOT EXISTS zinipay_payments (
            id SERIAL PRIMARY KEY, user_id BIGINT, plan TEXT, amount REAL,
            invoice_id TEXT UNIQUE, val_id TEXT, payment_url TEXT,
            status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT NOW(), verified_at TIMESTAMP)""")
        await c.execute("""CREATE TABLE IF NOT EXISTS voice_logs (
            id SERIAL PRIMARY KEY, user_id BIGINT, voice_name TEXT,
            text_length INTEGER, rating INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())""")
        await c.execute("CREATE TABLE IF NOT EXISTS favorite_voices (user_id BIGINT PRIMARY KEY, voice_name TEXT)")
        await c.execute("CREATE TABLE IF NOT EXISTS user_speed (user_id BIGINT PRIMARY KEY, speed REAL DEFAULT 0.75)")
        await c.execute("""CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY, discount_percent INTEGER, max_uses INTEGER,
            used_count INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1)""")
        await c.execute("""CREATE TABLE IF NOT EXISTS referrals (
            id SERIAL PRIMARY KEY, referrer_id BIGINT, referred_id BIGINT,
            bonus_voices INTEGER DEFAULT 3, created_at TIMESTAMP DEFAULT NOW())""")
        await c.execute("""CREATE TABLE IF NOT EXISTS reseller_sales (
            id SERIAL PRIMARY KEY, reseller_id BIGINT, buyer_id BIGINT,
            plan TEXT, amount REAL, commission REAL, created_at TIMESTAMP DEFAULT NOW())""")
        await c.execute("""CREATE TABLE IF NOT EXISTS streaks (
            user_id BIGINT PRIMARY KEY, current_streak INTEGER DEFAULT 0,
            last_used TEXT, max_streak INTEGER DEFAULT 0)""")
        await c.execute("""CREATE TABLE IF NOT EXISTS error_logs (
            id SERIAL PRIMARY KEY, user_id BIGINT, error TEXT, created_at TIMESTAMP DEFAULT NOW())""")
        await c.execute("""CREATE TABLE IF NOT EXISTS waitlist (
            id SERIAL PRIMARY KEY, user_id BIGINT, plan TEXT, created_at TIMESTAMP DEFAULT NOW())""")

async def upsert_user(user_id, username, full_name):
    import random, string
    ref = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("""INSERT INTO users (user_id,username,full_name,referral_code) VALUES($1,$2,$3,$4)
            ON CONFLICT(user_id) DO UPDATE SET username=EXCLUDED.username,full_name=EXCLUDED.full_name""",
            user_id, username or "", full_name or "", ref)

async def get_user(user_id):
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)

async def is_banned(user_id):
    u = await get_user(user_id); return bool(u and u["is_banned"])

async def ban_user(user_id):
    pool = await get_pool()
    async with pool.acquire() as c: await c.execute("UPDATE users SET is_banned=1 WHERE user_id=$1", user_id)

async def unban_user(user_id):
    pool = await get_pool()
    async with pool.acquire() as c: await c.execute("UPDATE users SET is_banned=0 WHERE user_id=$1", user_id)

async def get_active_subscription(user_id):
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetchrow("""SELECT * FROM subscriptions WHERE user_id=$1 AND is_active=1 AND expires_at>NOW()
            ORDER BY expires_at DESC LIMIT 1""", user_id)

async def can_use_voice(user_id):
    sub = await get_active_subscription(user_id)
    if not sub: return False, "no_sub"
    if sub["voices_used"] >= sub["voice_limit"]: return False, "limit_reached"
    return True, "ok"

async def increment_voice_usage(user_id):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("UPDATE subscriptions SET voices_used=voices_used+1 WHERE user_id=$1 AND is_active=1 AND expires_at>NOW()", user_id)

async def create_subscription(user_id, plan, bonus=0, gifted_by=None):
    plan_data = PLANS[plan]
    new_voices = plan_data["voice_limit"] + bonus
    expires = datetime.utcnow() + timedelta(days=plan_data["days"])
    started = datetime.utcnow()
    pool = await get_pool()
    async with pool.acquire() as c:
        existing = await c.fetchrow("SELECT * FROM subscriptions WHERE user_id=$1 AND is_active=1 AND expires_at>NOW() ORDER BY expires_at DESC LIMIT 1", user_id)
        if existing:
            total = existing["voice_limit"] - existing["voices_used"] + new_voices
            await c.execute("UPDATE subscriptions SET is_active=0 WHERE user_id=$1", user_id)
            await c.execute("INSERT INTO subscriptions(user_id,plan,voice_limit,voices_used,started_at,expires_at,gifted_by) VALUES($1,$2,$3,0,$4,$5,$6)", user_id, plan, total, started, expires, gifted_by)
        else:
            await c.execute("UPDATE subscriptions SET is_active=0 WHERE user_id=$1", user_id)
            await c.execute("INSERT INTO subscriptions(user_id,plan,voice_limit,voices_used,started_at,expires_at,gifted_by) VALUES($1,$2,$3,0,$4,$5,$6)", user_id, plan, new_voices, started, expires, gifted_by)

async def log_voice(user_id, voice_name, text_length):
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetchval("INSERT INTO voice_logs(user_id,voice_name,text_length) VALUES($1,$2,$3) RETURNING id", user_id, voice_name, text_length)

async def rate_voice(log_id, rating):
    pool = await get_pool()
    async with pool.acquire() as c: await c.execute("UPDATE voice_logs SET rating=$1 WHERE id=$2", rating, log_id)

async def get_voice_history(user_id, limit=5):
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetch("SELECT id,voice_name,text_length,rating,created_at FROM voice_logs WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2", user_id, limit)

async def get_total_voices(user_id):
    pool = await get_pool()
    async with pool.acquire() as c: return await c.fetchval("SELECT COUNT(*) FROM voice_logs WHERE user_id=$1", user_id)

async def get_user_speed(user_id):
    pool = await get_pool()
    async with pool.acquire() as c:
        v = await c.fetchval("SELECT speed FROM user_speed WHERE user_id=$1", user_id)
        return v if v is not None else 0.75

async def set_user_speed(user_id, speed):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("INSERT INTO user_speed(user_id,speed) VALUES($1,$2) ON CONFLICT(user_id) DO UPDATE SET speed=EXCLUDED.speed", user_id, speed)

async def get_favorite_voice(user_id):
    pool = await get_pool()
    async with pool.acquire() as c: return await c.fetchval("SELECT voice_name FROM favorite_voices WHERE user_id=$1", user_id)

async def set_favorite_voice(user_id, voice_name):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("INSERT INTO favorite_voices(user_id,voice_name) VALUES($1,$2) ON CONFLICT(user_id) DO UPDATE SET voice_name=EXCLUDED.voice_name", user_id, voice_name)

async def create_coupon(code, discount_percent, max_uses):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("INSERT INTO coupons(code,discount_percent,max_uses) VALUES($1,$2,$3) ON CONFLICT(code) DO UPDATE SET discount_percent=EXCLUDED.discount_percent,max_uses=EXCLUDED.max_uses", code.upper(), discount_percent, max_uses)

async def use_coupon(code):
    pool = await get_pool()
    async with pool.acquire() as c:
        coupon = await c.fetchrow("SELECT * FROM coupons WHERE code=$1 AND is_active=1 AND used_count<max_uses", code.upper())
        if not coupon: return None
        await c.execute("UPDATE coupons SET used_count=used_count+1 WHERE code=$1", code.upper())
        return coupon

async def get_referral_code(user_id):
    u = await get_user(user_id); return u["referral_code"] if u else None

async def process_referral(referrer_code, new_user_id):
    pool = await get_pool()
    async with pool.acquire() as c:
        referrer = await c.fetchrow("SELECT user_id FROM users WHERE referral_code=$1", referrer_code)
        if not referrer or referrer["user_id"] == new_user_id: return None
        rid = referrer["user_id"]
        await c.execute("UPDATE subscriptions SET voice_limit=voice_limit+3 WHERE user_id=$1 AND is_active=1 AND expires_at>NOW()", rid)
        await c.execute("INSERT INTO referrals(referrer_id,referred_id) VALUES($1,$2)", rid, new_user_id)
        await c.execute("UPDATE users SET referred_by=$1 WHERE user_id=$2", rid, new_user_id)
        return rid

async def create_reseller(user_id, commission_percent):
    import random, string
    code = "RS" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("UPDATE users SET reseller_code=$1,reseller_commission=$2 WHERE user_id=$3", code, commission_percent, user_id)
    return code

async def get_reseller_by_code(code):
    pool = await get_pool()
    async with pool.acquire() as c: return await c.fetchrow("SELECT * FROM users WHERE reseller_code=$1", code)

async def add_reseller_sale(reseller_id, buyer_id, plan, amount, commission):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("INSERT INTO reseller_sales(reseller_id,buyer_id,plan,amount,commission) VALUES($1,$2,$3,$4,$5)", reseller_id, buyer_id, plan, amount, commission)

async def save_payment(user_id, method, amount, plan, trx_id):
    pool = await get_pool()
    async with pool.acquire() as c:
        try:
            await c.execute("INSERT INTO payments(user_id,method,amount,plan,trx_id) VALUES($1,$2,$3,$4,$5)", user_id, method, amount, plan, trx_id)
            return True
        except: return False

async def approve_payment(trx_id):
    pool = await get_pool()
    async with pool.acquire() as c:
        p = await c.fetchrow("SELECT * FROM payments WHERE trx_id=$1 AND status='pending'", trx_id)
        if not p: return None
        await c.execute("UPDATE payments SET status='verified',verified_at=NOW() WHERE trx_id=$1", trx_id)
        return p

async def save_zinipay_payment(user_id, plan_key, amount, invoice_id, payment_url, val_id=""):
    pool = await get_pool()
    async with pool.acquire() as c:
        try:
            await c.execute("INSERT INTO zinipay_payments(user_id,plan,amount,invoice_id,val_id,payment_url) VALUES($1,$2,$3,$4,$5,$6)", user_id, plan_key, amount, invoice_id, val_id, payment_url)
        except Exception as e:
            import logging; logging.getLogger(__name__).error(f"ZiniPay DB error: {e}")

async def get_zinipay_payment(invoice_id):
    pool = await get_pool()
    async with pool.acquire() as c: return await c.fetchrow("SELECT * FROM zinipay_payments WHERE invoice_id=$1", invoice_id)

async def approve_zinipay_payment(invoice_id):
    pool = await get_pool()
    async with pool.acquire() as c:
        p = await c.fetchrow("SELECT * FROM zinipay_payments WHERE invoice_id=$1 AND status='pending'", invoice_id)
        if not p: return False
        await c.execute("UPDATE zinipay_payments SET status='verified',verified_at=NOW() WHERE invoice_id=$1", invoice_id)
    await create_subscription(p["user_id"], p["plan"])
    return True

async def get_pending_zinipay_payments():
    pool = await get_pool()
    async with pool.acquire() as c:
        try: return await c.fetch("SELECT z.*,u.full_name,u.username FROM zinipay_payments z LEFT JOIN users u ON z.user_id=u.user_id WHERE z.status='pending' ORDER BY z.created_at DESC LIMIT 10")
        except: return []

async def get_expiring_soon(days=3):
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetch("SELECT user_id,plan,expires_at FROM subscriptions WHERE is_active=1 AND expires_at>NOW() AND expires_at<NOW()+($1||' days')::INTERVAL", str(days))

async def get_inactive_users(days=7):
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetch(f"SELECT DISTINCT u.user_id,u.full_name FROM users u LEFT JOIN voice_logs v ON u.user_id=v.user_id WHERE u.is_banned=0 AND (v.created_at<NOW()-INTERVAL '{days} days' OR v.created_at IS NULL)")

async def get_leaderboard(limit=10):
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetch("SELECT u.full_name,u.user_id,COUNT(v.id) as total FROM users u LEFT JOIN voice_logs v ON u.user_id=v.user_id WHERE u.is_banned=0 GROUP BY u.user_id,u.full_name ORDER BY total DESC LIMIT $1", limit)

async def get_admin_stats():
    pool = await get_pool()
    async with pool.acquire() as c:
        return {
            "total_users":      await c.fetchval("SELECT COUNT(*) FROM users") or 0,
            "active_subs":      await c.fetchval("SELECT COUNT(*) FROM subscriptions WHERE is_active=1 AND expires_at>NOW()") or 0,
            "total_voices":     await c.fetchval("SELECT COUNT(*) FROM voice_logs") or 0,
            "total_payments":   await c.fetchval("SELECT COUNT(*) FROM payments WHERE status='verified'") or 0,
            "pending_payments": await c.fetchval("SELECT COUNT(*) FROM payments WHERE status='pending'") or 0,
            "total_revenue":    await c.fetchval("SELECT SUM(amount) FROM payments WHERE status='verified'") or 0,
            "avg_rating":       round(float(await c.fetchval("SELECT AVG(rating) FROM voice_logs WHERE rating>0") or 0), 1),
        }

async def get_pending_payments():
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetch("SELECT p.*,u.username,u.full_name FROM payments p LEFT JOIN users u ON p.user_id=u.user_id WHERE p.status='pending' ORDER BY p.created_at DESC LIMIT 10")

async def get_all_users():
    pool = await get_pool()
    async with pool.acquire() as c:
        return await c.fetch("SELECT u.*,s.plan,s.voices_used,s.voice_limit,s.expires_at FROM users u LEFT JOIN subscriptions s ON u.user_id=s.user_id AND s.is_active=1 ORDER BY u.joined_at DESC LIMIT 20")

async def get_all_user_ids():
    pool = await get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch("SELECT user_id FROM users WHERE is_banned=0")
        return [r["user_id"] for r in rows]

async def get_sales_report():
    pool = await get_pool()
    async with pool.acquire() as c:
        return {
            "by_plan":   await c.fetch("SELECT plan,COUNT(*) as count,SUM(amount) as total FROM payments WHERE status='verified' GROUP BY plan"),
            "by_method": await c.fetch("SELECT method,COUNT(*) as count,SUM(amount) as total FROM payments WHERE status='verified' GROUP BY method"),
            "monthly":   await c.fetchval("SELECT SUM(amount) FROM payments WHERE status='verified' AND created_at>NOW()-INTERVAL '30 days'") or 0,
            "weekly":    await c.fetchval("SELECT SUM(amount) FROM payments WHERE status='verified' AND created_at>NOW()-INTERVAL '7 days'") or 0,
        }

async def update_streak(user_id):
    today = datetime.utcnow().date().isoformat()
    yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
    pool = await get_pool()
    async with pool.acquire() as c:
        row = await c.fetchrow("SELECT * FROM streaks WHERE user_id=$1", user_id)
        if not row:
            await c.execute("INSERT INTO streaks(user_id,current_streak,last_used,max_streak) VALUES($1,1,$2,1)", user_id, today)
        else:
            last = row["last_used"]
            if last == today: pass
            elif last == yesterday:
                ns = row["current_streak"] + 1
                await c.execute("UPDATE streaks SET current_streak=$1,last_used=$2,max_streak=$3 WHERE user_id=$4", ns, today, max(ns, row["max_streak"]), user_id)
            else:
                await c.execute("UPDATE streaks SET current_streak=1,last_used=$1 WHERE user_id=$2", today, user_id)

async def get_streak(user_id):
    pool = await get_pool()
    async with pool.acquire() as c: return await c.fetchrow("SELECT * FROM streaks WHERE user_id=$1", user_id)

async def set_birthday(user_id, birthday):
    pool = await get_pool()
    async with pool.acquire() as c: await c.execute("UPDATE users SET birthday=$1 WHERE user_id=$2", birthday, user_id)

async def get_birthday_users():
    today = datetime.utcnow().strftime("%m-%d")
    pool = await get_pool()
    async with pool.acquire() as c:
        try: return await c.fetch("SELECT user_id,full_name FROM users WHERE birthday LIKE $1", f"%-{today}")
        except: return []

async def log_error(error_msg, user_id=None):
    pool = await get_pool()
    async with pool.acquire() as c:
        try: await c.execute("INSERT INTO error_logs(user_id,error) VALUES($1,$2)", user_id, str(error_msg)[:500])
        except: pass

async def get_error_logs(limit=10):
    pool = await get_pool()
    async with pool.acquire() as c:
        try: return await c.fetch("SELECT * FROM error_logs ORDER BY created_at DESC LIMIT $1", limit)
        except: return []

async def search_user(query):
    pool = await get_pool()
    async with pool.acquire() as c:
        try:
            uid = int(query)
            row = await c.fetchrow("SELECT * FROM users WHERE user_id=$1", uid)
            return [row] if row else []
        except ValueError:
            return await c.fetch("SELECT * FROM users WHERE full_name ILIKE $1 OR username ILIKE $1 LIMIT 5", f"%{query}%")

async def add_to_waitlist(user_id, plan):
    pool = await get_pool()
    async with pool.acquire() as c:
        try: await c.execute("INSERT INTO waitlist(user_id,plan) VALUES($1,$2)", user_id, plan)
        except: pass

async def get_waitlist():
    pool = await get_pool()
    async with pool.acquire() as c:
        try: return await c.fetch("SELECT w.*,u.full_name,u.username FROM waitlist w LEFT JOIN users u ON w.user_id=u.user_id ORDER BY w.created_at ASC")
        except: return []

async def give_free_voices(user_id, amount):
    pool = await get_pool()
    async with pool.acquire() as c:
        await c.execute("UPDATE subscriptions SET voice_limit=voice_limit+$1 WHERE user_id=$2 AND is_active=1 AND expires_at>NOW()", amount, user_id)
