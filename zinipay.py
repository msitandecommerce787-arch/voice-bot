"""
zinipay.py — ZiniPay Payment Integration
ZiniPay API দিয়ে automatic payment link বানায় ও verify করে
"""

import os
import logging
import aiosqlite
import httpx
from datetime import datetime
import database as db

logger = logging.getLogger(__name__)

ZINIPAY_API_KEY = os.environ.get("ZINIPAY_API_KEY", "")
ZINIPAY_BASE_URL = "https://api.zinipay.com"
BOT_BASE_URL = os.environ.get("BOT_BASE_URL", "https://yourdomain.com")  # তোমার server URL


async def create_zinipay_invoice(user_id: int, plan_key: str, amount: int, user_name: str = "", user_email: str = "") -> dict | None:
    """
    ZiniPay এ invoice বানাও, payment URL return করো
    """
    if not ZINIPAY_API_KEY:
        logger.error("ZINIPAY_API_KEY set নেই!")
        return None

    plan = db.PLANS.get(plan_key, {})
    val_id = f"ZINI-{user_id}-{plan_key}-{int(datetime.utcnow().timestamp())}"

    payload = {
        "cus_name": user_name or f"User_{user_id}",
        "cus_email": user_email or f"user{user_id}@voicebot.com",
        "amount": amount,
        "metadata": {
            "user_id": str(user_id),
            "plan": plan_key,
            "bot": "voice_bot"
        },
        "redirect_url": f"{BOT_BASE_URL}/payment/success",
        "cancel_url": f"{BOT_BASE_URL}/payment/cancel",
        "val_id": val_id,
        "webhook_url": f"{BOT_BASE_URL}/webhook/zinipay",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{ZINIPAY_BASE_URL}/v1/payment/create",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "zini-api-key": ZINIPAY_API_KEY,
                },
            )
            data = resp.json()
            if data.get("status") and data.get("payment_url"):
                # Database এ pending হিসেবে save করো
                await save_zinipay_payment(user_id, plan_key, amount, val_id, data["payment_url"])
                return {
                    "payment_url": data["payment_url"],
                    "val_id": val_id,
                    "invoice_id": data.get("payment_url", "").split("/")[-1],
                }
            else:
                logger.error(f"ZiniPay create failed: {data}")
                return None
    except Exception as e:
        logger.error(f"ZiniPay API error: {e}")
        return None


async def verify_zinipay_invoice(invoice_id: str) -> dict | None:
    """
    ZiniPay এ invoice status verify করো
    """
    if not ZINIPAY_API_KEY:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{ZINIPAY_BASE_URL}/v1/payment/verify",
                json={"invoice_id": invoice_id},
                headers={
                    "Content-Type": "application/json",
                    "zini-api-key": ZINIPAY_API_KEY,
                },
            )
            data = resp.json()
            return data
    except Exception as e:
        logger.error(f"ZiniPay verify error: {e}")
        return None


async def save_zinipay_payment(user_id: int, plan_key: str, amount: int, val_id: str, payment_url: str):
    """ZiniPay payment টা database এ save করো"""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS zinipay_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    plan TEXT,
                    amount REAL,
                    val_id TEXT UNIQUE,
                    payment_url TEXT,
                    status TEXT DEFAULT 'pending',
                    invoice_id TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    verified_at TEXT
                )
            """)
            await conn.execute("""
                INSERT INTO zinipay_payments (user_id, plan, amount, val_id, payment_url)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, plan_key, amount, val_id, payment_url))
            await conn.commit()
        except Exception as e:
            logger.error(f"ZiniPay DB save error: {e}")


async def get_zinipay_payment_by_val_id(val_id: str):
    """val_id দিয়ে ZiniPay payment খোঁজো"""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM zinipay_payments WHERE val_id=?", (val_id,)
        ) as cur:
            return await cur.fetchone()


async def approve_zinipay_payment(val_id: str) -> bool:
    """ZiniPay payment approve করো ও subscription activate করো"""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM zinipay_payments WHERE val_id=? AND status='pending'", (val_id,)
        ) as cur:
            payment = await cur.fetchone()

        if not payment:
            return False

        await conn.execute("""
            UPDATE zinipay_payments SET status='verified', verified_at=datetime('now')
            WHERE val_id=?
        """, (val_id,))
        await conn.commit()

    await db.create_subscription(payment["user_id"], payment["plan"])
    return True


async def get_pending_zinipay_payments():
    """সব pending ZiniPay payment দেখো"""
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        try:
            async with conn.execute("""
                SELECT z.*, u.full_name, u.username
                FROM zinipay_payments z
                LEFT JOIN users u ON z.user_id = u.user_id
                WHERE z.status='pending'
                ORDER BY z.created_at DESC LIMIT 10
            """) as cur:
                return await cur.fetchall()
        except Exception:
            return []
