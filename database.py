import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
import threading

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

_local = threading.local()

def get_conn():
    if not hasattr(_local, 'conn') or _local.conn.closed:
        _local.conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        _local.conn.autocommit = False
    return _local.conn

def execute(query, params=None, fetch=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            conn.commit()
            if fetch == "one":
                return cur.fetchone()
            elif fetch == "all":
                return cur.fetchall()
            elif fetch == "val":
                row = cur.fetchone()
                return list(row.values())[0] if row else None
            elif fetch == "lastid":
                cur.execute("SELECT lastval()")
                return cur.fetchone()["lastval"]
    except Exception as e:
        conn.rollback()
        raise e

async def init_db():
    execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            joined_at TIMESTAMP DEFAULT NOW(),
            is_banned INTEGER DEFAULT 0,
            referral_code TEXT,
            referred_by BIGINT,
            reseller_code TEXT,
            reseller_commission INTEGER DEFAULT 0,
            birthday TEXT
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            plan TEXT,
            voice_limit INTEGER,
            voices_used INTEGER DEFAULT 0,
            started_at TIMESTAMP,
            expires_at TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            gifted_by BIGINT DEFAULT NULL
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            method TEXT,
            amount REAL,
            plan TEXT,
            trx_id TEXT UNIQUE,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW(),
            verified_at TIMESTAMP
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS zinipay_payments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            plan TEXT,
            amount REAL,
            invoice_id TEXT UNIQUE,
            val_id TEXT,
            payment_url TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW(),
            verified_at TIMESTAMP
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS voice_logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            voice_name TEXT,
            text_length INTEGER,
            rating INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    execute("CREATE TABLE IF NOT EXISTS favorite_voices (user_id BIGINT PRIMARY KEY, voice_name TEXT)")
    execute("CREATE TABLE IF NOT EXISTS user_speed (user_id BIGINT PRIMARY KEY, speed REAL DEFAULT 0.75)")
    execute("""
        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY,
            discount_percent INTEGER,
            max_uses INTEGER,
            used_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id SERIAL PRIMARY KEY,
            referrer_id BIGINT,
            referred_id BIGINT,
            bonus_voices INTEGER DEFAULT 3,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS reseller_sales (
            id SERIAL PRIMARY KEY,
            reseller_id BIGINT,
            buyer_id BIGINT,
            plan TEXT,
            amount REAL,
            commission REAL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS streaks (
            user_id BIGINT PRIMARY KEY,
            current_streak INTEGER DEFAULT 0,
            last_used TEXT,
            max_streak INTEGER DEFAULT 0
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS error_logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            error TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            plan TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

# ── USER ──────────────────────────────────────────────────────
async def upsert_user(user_id, username, full_name):
    import random, string
    ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    execute("""
        INSERT INTO users (user_id, username, full_name, referral_code)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT(user_id) DO UPDATE SET username=EXCLUDED.username, full_name=EXCLUDED.full_name
    """, (user_id, username or "", full_name or "", ref_code))

async def get_user(user_id):
    return execute("SELECT * FROM users WHERE user_id=%s", (user_id,), fetch="one")

async def is_banned(user_id):
    user = await get_user(user_id)
    return bool(user and user["is_banned"])

async def ban_user(user_id):
    execute("UPDATE users SET is_banned=1 WHERE user_id=%s", (user_id,))

async def unban_user(user_id):
    execute("UPDATE users SET is_banned=0 WHERE user_id=%s", (user_id,))

# ── SUBSCRIPTION ──────────────────────────────────────────────
async def get_active_subscription(user_id):
    return execute("""
        SELECT * FROM subscriptions
        WHERE user_id=%s AND is_active=1 AND expires_at > NOW()
        ORDER BY expires_at DESC LIMIT 1
    """, (user_id,), fetch="one")

async def can_use_voice(user_id):
    sub = await get_active_subscription(user_id)
    if not sub:
        return False, "no_sub"
    if sub["voices_used"] >= sub["voice_limit"]:
        return False, "limit_reached"
    return True, "ok"

async def increment_voice_usage(user_id):
    execute("""
        UPDATE subscriptions SET voices_used = voices_used + 1
        WHERE user_id=%s AND is_active=1 AND expires_at > NOW()
    """, (user_id,))

async def create_subscription(user_id, plan, bonus=0, gifted_by=None):
    plan_data = PLANS[plan]
    new_voices = plan_data["voice_limit"] + bonus
    expires = datetime.utcnow() + timedelta(days=plan_data["days"])
    started = datetime.utcnow()
    existing = execute("""
        SELECT * FROM subscriptions WHERE user_id=%s AND is_active=1 AND expires_at > NOW()
        ORDER BY expires_at DESC LIMIT 1
    """, (user_id,), fetch="one")
    if existing:
        remaining = existing["voice_limit"] - existing["voices_used"]
        total_voices = remaining + new_voices
        execute("UPDATE subscriptions SET is_active=0 WHERE user_id=%s", (user_id,))
        execute("""
            INSERT INTO subscriptions (user_id, plan, voice_limit, voices_used, started_at, expires_at, gifted_by)
            VALUES (%s, %s, %s, 0, %s, %s, %s)
        """, (user_id, plan, total_voices, started, expires, gifted_by))
    else:
        execute("UPDATE subscriptions SET is_active=0 WHERE user_id=%s", (user_id,))
        execute("""
            INSERT INTO subscriptions (user_id, plan, voice_limit, voices_used, started_at, expires_at, gifted_by)
            VALUES (%s, %s, %s, 0, %s, %s, %s)
        """, (user_id, plan, new_voices, started, expires, gifted_by))

# ── VOICE LOG ─────────────────────────────────────────────────
async def log_voice(user_id, voice_name, text_length):
    execute("""
        INSERT INTO voice_logs (user_id, voice_name, text_length) VALUES (%s, %s, %s)
    """, (user_id, voice_name, text_length))
    return execute("SELECT lastval()", fetch="val")

async def rate_voice(log_id, rating):
    execute("UPDATE voice_logs SET rating=%s WHERE id=%s", (rating, log_id))

async def get_voice_history(user_id, limit=5):
    return execute("""
        SELECT id, voice_name, text_length, rating, created_at FROM voice_logs
        WHERE user_id=%s ORDER BY created_at DESC LIMIT %s
    """, (user_id, limit), fetch="all") or []

async def get_total_voices(user_id):
    return execute("SELECT COUNT(*) as c FROM voice_logs WHERE user_id=%s", (user_id,), fetch="val") or 0

# ── SPEED & FAVORITE ──────────────────────────────────────────
async def get_user_speed(user_id):
    row = execute("SELECT speed FROM user_speed WHERE user_id=%s", (user_id,), fetch="one")
    return row["speed"] if row else 0.75

async def set_user_speed(user_id, speed):
    execute("""
        INSERT INTO user_speed (user_id, speed) VALUES (%s, %s)
        ON CONFLICT(user_id) DO UPDATE SET speed=EXCLUDED.speed
    """, (user_id, speed))

async def get_favorite_voice(user_id):
    row = execute("SELECT voice_name FROM favorite_voices WHERE user_id=%s", (user_id,), fetch="one")
    return row["voice_name"] if row else None

async def set_favorite_voice(user_id, voice_name):
    execute("""
        INSERT INTO favorite_voices (user_id, voice_name) VALUES (%s, %s)
        ON CONFLICT(user_id) DO UPDATE SET voice_name=EXCLUDED.voice_name
    """, (user_id, voice_name))

# ── COUPON ────────────────────────────────────────────────────
async def create_coupon(code, discount_percent, max_uses):
    execute("""
        INSERT INTO coupons (code, discount_percent, max_uses) VALUES (%s, %s, %s)
        ON CONFLICT(code) DO UPDATE SET discount_percent=EXCLUDED.discount_percent, max_uses=EXCLUDED.max_uses
    """, (code.upper(), discount_percent, max_uses))

async def use_coupon(code):
    coupon = execute("""
        SELECT * FROM coupons WHERE code=%s AND is_active=1 AND used_count < max_uses
    """, (code.upper(),), fetch="one")
    if not coupon:
        return None
    execute("UPDATE coupons SET used_count = used_count + 1 WHERE code=%s", (code.upper(),))
    return coupon

# ── REFERRAL ──────────────────────────────────────────────────
async def get_referral_code(user_id):
    user = await get_user(user_id)
    return user["referral_code"] if user else None

async def process_referral(referrer_code, new_user_id):
    referrer = execute("SELECT user_id FROM users WHERE referral_code=%s", (referrer_code,), fetch="one")
    if not referrer or referrer["user_id"] == new_user_id:
        return None
    referrer_id = referrer["user_id"]
    execute("""
        UPDATE subscriptions SET voice_limit = voice_limit + 3
        WHERE user_id=%s AND is_active=1 AND expires_at > NOW()
    """, (referrer_id,))
    execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (%s, %s)", (referrer_id, new_user_id))
    execute("UPDATE users SET referred_by=%s WHERE user_id=%s", (referrer_id, new_user_id))
    return referrer_id

# ── RESELLER ──────────────────────────────────────────────────
async def create_reseller(user_id, commission_percent):
    import random, string
    code = "RS" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    execute("UPDATE users SET reseller_code=%s, reseller_commission=%s WHERE user_id=%s", (code, commission_percent, user_id))
    return code

async def get_reseller_by_code(code):
    return execute("SELECT * FROM users WHERE reseller_code=%s", (code,), fetch="one")

async def add_reseller_sale(reseller_id, buyer_id, plan, amount, commission):
    execute("""
        INSERT INTO reseller_sales (reseller_id, buyer_id, plan, amount, commission)
        VALUES (%s, %s, %s, %s, %s)
    """, (reseller_id, buyer_id, plan, amount, commission))

# ── PAYMENT ───────────────────────────────────────────────────
async def save_payment(user_id, method, amount, plan, trx_id):
    try:
        execute("""
            INSERT INTO payments (user_id, method, amount, plan, trx_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, method, amount, plan, trx_id))
        return True
    except Exception:
        return False

async def approve_payment(trx_id):
    payment = execute("SELECT * FROM payments WHERE trx_id=%s AND status='pending'", (trx_id,), fetch="one")
    if not payment:
        return None
    execute("UPDATE payments SET status='verified', verified_at=NOW() WHERE trx_id=%s", (trx_id,))
    return payment

# ── ZINIPAY ───────────────────────────────────────────────────
async def save_zinipay_payment(user_id, plan_key, amount, invoice_id, payment_url, val_id=""):
    try:
        execute("""
            INSERT INTO zinipay_payments (user_id, plan, amount, invoice_id, val_id, payment_url)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, plan_key, amount, invoice_id, val_id, payment_url))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"ZiniPay DB save error: {e}")

async def get_zinipay_payment(invoice_id):
    return execute("SELECT * FROM zinipay_payments WHERE invoice_id=%s", (invoice_id,), fetch="one")

async def approve_zinipay_payment(invoice_id):
    payment = execute("SELECT * FROM zinipay_payments WHERE invoice_id=%s AND status='pending'", (invoice_id,), fetch="one")
    if not payment:
        return False
    execute("UPDATE zinipay_payments SET status='verified', verified_at=NOW() WHERE invoice_id=%s", (invoice_id,))
    await create_subscription(payment["user_id"], payment["plan"])
    return True

async def get_pending_zinipay_payments():
    return execute("""
        SELECT z.*, u.full_name, u.username
        FROM zinipay_payments z
        LEFT JOIN users u ON z.user_id = u.user_id
        WHERE z.status='pending'
        ORDER BY z.created_at DESC LIMIT 10
    """, fetch="all") or []

# ── EXPIRY ────────────────────────────────────────────────────
async def get_expiring_soon(days=3):
    return execute("""
        SELECT user_id, plan, expires_at FROM subscriptions
        WHERE is_active=1 AND expires_at > NOW()
        AND expires_at < NOW() + INTERVAL '%s days'
    """, (days,), fetch="all") or []

async def get_inactive_users(days=7):
    return execute(f"""
        SELECT DISTINCT u.user_id, u.full_name FROM users u
        LEFT JOIN voice_logs v ON u.user_id = v.user_id
        WHERE u.is_banned=0
        AND (v.created_at < NOW() - INTERVAL '{days} days' OR v.created_at IS NULL)
    """, fetch="all") or []

# ── LEADERBOARD ───────────────────────────────────────────────
async def get_leaderboard(limit=10):
    return execute("""
        SELECT u.full_name, u.user_id, COUNT(v.id) as total
        FROM users u
        LEFT JOIN voice_logs v ON u.user_id = v.user_id
        WHERE u.is_banned=0
        GROUP BY u.user_id, u.full_name
        ORDER BY total DESC LIMIT %s
    """, (limit,), fetch="all") or []

# ── ADMIN STATS ───────────────────────────────────────────────
async def get_admin_stats():
    stats = {}
    stats["total_users"]      = execute("SELECT COUNT(*) as c FROM users", fetch="val") or 0
    stats["active_subs"]      = execute("SELECT COUNT(*) as c FROM subscriptions WHERE is_active=1 AND expires_at > NOW()", fetch="val") or 0
    stats["total_voices"]     = execute("SELECT COUNT(*) as c FROM voice_logs", fetch="val") or 0
    stats["total_payments"]   = execute("SELECT COUNT(*) as c FROM payments WHERE status='verified'", fetch="val") or 0
    stats["pending_payments"] = execute("SELECT COUNT(*) as c FROM payments WHERE status='pending'", fetch="val") or 0
    rev = execute("SELECT SUM(amount) as s FROM payments WHERE status='verified'", fetch="val")
    stats["total_revenue"] = rev or 0
    avg = execute("SELECT AVG(rating) as a FROM voice_logs WHERE rating > 0", fetch="val")
    stats["avg_rating"] = round(float(avg or 0), 1)
    return stats

async def get_pending_payments():
    return execute("""
        SELECT p.*, u.username, u.full_name FROM payments p
        LEFT JOIN users u ON p.user_id = u.user_id
        WHERE p.status='pending' ORDER BY p.created_at DESC LIMIT 10
    """, fetch="all") or []

async def get_all_users():
    return execute("""
        SELECT u.*, s.plan, s.voices_used, s.voice_limit, s.expires_at
        FROM users u
        LEFT JOIN subscriptions s ON u.user_id = s.user_id AND s.is_active=1
        ORDER BY u.joined_at DESC LIMIT 20
    """, fetch="all") or []

async def get_all_user_ids():
    rows = execute("SELECT user_id FROM users WHERE is_banned=0", fetch="all") or []
    return [r["user_id"] for r in rows]

async def get_sales_report():
    report = {}
    report["by_plan"]   = execute("SELECT plan, COUNT(*) as count, SUM(amount) as total FROM payments WHERE status='verified' GROUP BY plan", fetch="all") or []
    report["by_method"] = execute("SELECT method, COUNT(*) as count, SUM(amount) as total FROM payments WHERE status='verified' GROUP BY method", fetch="all") or []
    report["monthly"]   = execute("SELECT SUM(amount) as s FROM payments WHERE status='verified' AND created_at > NOW() - INTERVAL '30 days'", fetch="val") or 0
    report["weekly"]    = execute("SELECT SUM(amount) as s FROM payments WHERE status='verified' AND created_at > NOW() - INTERVAL '7 days'", fetch="val") or 0
    return report

# ── STREAK ────────────────────────────────────────────────────
async def update_streak(user_id):
    today = datetime.utcnow().date().isoformat()
    yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
    row = execute("SELECT * FROM streaks WHERE user_id=%s", (user_id,), fetch="one")
    if not row:
        execute("INSERT INTO streaks (user_id, current_streak, last_used, max_streak) VALUES (%s, 1, %s, 1)", (user_id, today))
    else:
        last = row["last_used"]
        if last == today:
            pass
        elif last == yesterday:
            new_streak = row["current_streak"] + 1
            max_s = max(new_streak, row["max_streak"])
            execute("UPDATE streaks SET current_streak=%s, last_used=%s, max_streak=%s WHERE user_id=%s", (new_streak, today, max_s, user_id))
        else:
            execute("UPDATE streaks SET current_streak=1, last_used=%s WHERE user_id=%s", (today, user_id))

async def get_streak(user_id):
    return execute("SELECT * FROM streaks WHERE user_id=%s", (user_id,), fetch="one")

# ── BIRTHDAY ──────────────────────────────────────────────────
async def set_birthday(user_id, birthday):
    execute("UPDATE users SET birthday=%s WHERE user_id=%s", (birthday, user_id))

async def get_birthday_users():
    today = datetime.utcnow().strftime("%m-%d")
    return execute("SELECT user_id, full_name FROM users WHERE birthday LIKE %s", (f"%-{today}",), fetch="all") or []

# ── ERROR LOG ─────────────────────────────────────────────────
async def log_error(error_msg, user_id=None):
    try:
        execute("INSERT INTO error_logs (user_id, error) VALUES (%s, %s)", (user_id, str(error_msg)[:500]))
    except Exception:
        pass

async def get_error_logs(limit=10):
    return execute("SELECT * FROM error_logs ORDER BY created_at DESC LIMIT %s", (limit,), fetch="all") or []

# ── USER SEARCH ───────────────────────────────────────────────
async def search_user(query):
    try:
        user_id = int(query)
        row = execute("SELECT * FROM users WHERE user_id=%s", (user_id,), fetch="one")
        return [row] if row else []
    except ValueError:
        return execute("SELECT * FROM users WHERE full_name ILIKE %s OR username ILIKE %s LIMIT 5", (f"%{query}%", f"%{query}%"), fetch="all") or []

# ── WAITLIST ──────────────────────────────────────────────────
async def add_to_waitlist(user_id, plan):
    try:
        execute("INSERT INTO waitlist (user_id, plan) VALUES (%s, %s)", (user_id, plan))
    except Exception:
        pass

async def get_waitlist():
    return execute("""
        SELECT w.*, u.full_name, u.username FROM waitlist w
        LEFT JOIN users u ON w.user_id = u.user_id ORDER BY w.created_at ASC
    """, fetch="all") or []

# ── GIVE FREE VOICES ──────────────────────────────────────────
async def give_free_voices(user_id, amount):
    execute("""
        UPDATE subscriptions SET voice_limit = voice_limit + %s
        WHERE user_id=%s AND is_active=1 AND expires_at > NOW()
    """, (amount, user_id))
