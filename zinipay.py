"""
zinipay.py — ZiniPay Payment Integration (Fixed)
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


async def create_zinipay_invoice(user_id: int, plan_key: str, amount: int, user_name: str = "") -> dict | None:
    if not ZINIPAY_API_KEY:
        logger.error("ZINIPAY_API_KEY set নেই!")
        return None

    plan = db.PLANS.get(plan_key, {})
    invoice_id = f"INV-{user_id}-{int(datetime.utcnow().timestamp())}"

    payload = {
        "cus_name": user_name or f"User_{user_id}",
        "cus_email": f"user{user_id}@voicebot.com",
        "amount": amount,
        "invoice_id": invoice_id,
        "val_id": invoice_id,
        "redirect_url": "https://t.me/Ms_voice_bot",
        "cancel_url": "https://t.me/Ms_voice_bot",
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
            logger.info(f"ZiniPay create response: {data}")

            if data.get("status") and data.get("payment_url"):
                zini_val_id = data.get("val_id", invoice_id)
                await save_zinipay_payment(user_id, plan_key, amount, invoice_id, data["payment_url"], zini_val_id)
                return {
                    "payment_url": data["payment_url"],
                    "invoice_id": invoice_id,
                    "val_id": zini_val_id,
                }
            else:
                logger.error(f"ZiniPay create failed: {data}")
                return None
    except Exception as e:
        logger.error(f"ZiniPay API error: {e}")
        return None


async def verify_zinipay_invoice(val_id: str) -> dict | None:
    if not ZINIPAY_API_KEY:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{ZINIPAY_BASE_URL}/v1/payment/verify",
                json={"invoice_id": val_id},
                headers={
                    "Content-Type": "application/json",
                    "zini-api-key": ZINIPAY_API_KEY,
                },
            )
            data = resp.json()
            logger.info(f"ZiniPay verify response: {data}")
            return data
    except Exception as e:
        logger.error(f"ZiniPay verify error: {e}")
        return None


async def save_zinipay_payment(user_id: int, plan_key: str, amount: int, invoice_id: str, payment_url: str, val_id: str = ""):
    async with aiosqlite.connect(db.DB_PATH) as conn:
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS zinipay_payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    plan TEXT,
                    amount REAL,
                    invoice_id TEXT UNIQUE,
                    val_id TEXT,
                    payment_url TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now')),
                    verified_at TEXT
                )
            """)
            await conn.execute("""
                INSERT INTO zinipay_payments (user_id, plan, amount, invoice_id, val_id, payment_url)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, plan_key, amount, invoice_id, val_id, payment_url))
            await conn.commit()
        except Exception as e:
            logger.error(f"ZiniPay DB save error: {e}")


async def get_zinipay_payment(invoice_id: str):
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM zinipay_payments WHERE invoice_id=?", (invoice_id,)
        ) as cur:
            return await cur.fetchone()


async def approve_zinipay_payment(invoice_id: str) -> bool:
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM zinipay_payments WHERE invoice_id=? AND status='pending'", (invoice_id,)
        ) as cur:
            payment = await cur.fetchone()

        if not payment:
            return False

        await conn.execute("""
            UPDATE zinipay_payments SET status='verified', verified_at=datetime('now')
            WHERE invoice_id=?
        """, (invoice_id,))
        await conn.commit()

    await db.create_subscription(payment["user_id"], payment["plan"])
    return True


async def get_pending_zinipay_payments():
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
