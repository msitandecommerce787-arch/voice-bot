"""
zinipay.py — ZiniPay Payment Integration (Postgres version)
"""

import os
import logging
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
                await db.save_zinipay_payment(user_id, plan_key, amount, invoice_id, data["payment_url"], zini_val_id)
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


async def verify_zinipay_invoice(invoice_id: str) -> dict | None:
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
            logger.info(f"ZiniPay verify response: {data}")
            return data
    except Exception as e:
        logger.error(f"ZiniPay verify error: {e}")
        return None
