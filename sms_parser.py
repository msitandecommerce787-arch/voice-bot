"""
sms_parser.py — SMS Auto Payment Verification (Fixed v2)
"""

import re
import logging
from telegram import Update
from telegram.ext import ContextTypes
import database as db

logger = logging.getLogger(__name__)

BKASH_PATTERNS = [
    # Received SMS
    r'received\s+Tk\s+([\d,]+\.?\d*).*?TrxID\s+([A-Z0-9]+)',
    r'Tk\s+([\d,]+\.?\d*)\s+has been credited.*?TrxID\s+([A-Z0-9]+)',
    r'(?:Tk|BDT)\s*([\d,]+\.?\d*).*?TrxID\s*:?\s*([A-Z0-9]{6,})',
    # ✅ NEW: Sent/Payment successful SMS
    r'Payment of Tk\s*([\d,]+\.?\d*).*?TrxID\s+([A-Z0-9]+)',
    r'Tk\s*([\d,]+\.?\d*).*?successful.*?TrxID\s+([A-Z0-9]+)',
    r'TrxID\s+([A-Z0-9]+).*?Tk\s*([\d,]+\.?\d*)',
]

NAGAD_PATTERNS = [
    r'Amount:\s*Tk\s*([\d,]+\.?\d*).*?TxnID:\s*([A-Z0-9]+)',
    r'Tk\s*([\d,]+\.?\d*).*?TxnID:\s*([A-Z0-9]+)',
    r'Amount.*?([\d,]+\.?\d*).*?TxnID\s*:?\s*([A-Z0-9]+)',
    # ✅ NEW: Nagad sent patterns
    r'(?:Tk|BDT)\s*([\d,]+\.?\d*).*?TxnID\s*:?\s*([A-Z0-9]{4,})',
    r'TxnID:\s*([A-Z0-9]+).*?Tk\s*([\d,]+\.?\d*)',
]

BANK_PATTERNS = [
    r'BDT\s*([\d,]+\.?\d*).+?(?:TxnId|TxID|TrxID)\s*:?\s*([A-Z0-9]+)',
    r'(?:credited|received)\s+(?:BDT|Tk)\s*([\d,]+\.?\d*).+?(?:TxnId|TrxID)\s*:?\s*([A-Z0-9]+)',
]


def parse_sms(sender: str, message: str) -> dict | None:
    sender_lower = sender.lower()
    message_clean = message.strip().replace('\\n', '\n')

    if any(x in sender_lower for x in ['bkash', 'b-kash', '16247']):
        patterns = BKASH_PATTERNS
        method = 'bkash'
    elif any(x in sender_lower for x in ['nagad', 'nagad-er', '16167']):
        patterns = NAGAD_PATTERNS
        method = 'nagad'
    else:
        patterns = BKASH_PATTERNS + NAGAD_PATTERNS + BANK_PATTERNS
        method = 'bank'
        if 'bkash' in message_clean.lower():
            method = 'bkash'
            patterns = BKASH_PATTERNS
        elif 'nagad' in message_clean.lower():
            method = 'nagad'
            patterns = NAGAD_PATTERNS

    for pattern in patterns:
        match = re.search(pattern, message_clean, re.IGNORECASE | re.DOTALL)
        if match:
            try:
                g1, g2 = match.group(1).strip(), match.group(2).strip()
                # TrxID আগে আসতে পারে বা পরে — amount সবসময় numeric
                try:
                    amount = float(g1.replace(',', ''))
                    trx_id = g2
                except ValueError:
                    amount = float(g2.replace(',', ''))
                    trx_id = g1

                if amount > 0 and len(trx_id) >= 4:
                    return {
                        "amount": amount,
                        "trx_id": trx_id,
                        "method": method,
                        "raw_sms": message_clean[:200]
                    }
            except (ValueError, IndexError):
                continue

    return None


async def find_matching_payment(amount: float, trx_id: str, method: str):
    import aiosqlite
    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM payments WHERE trx_id=? AND status='pending'", (trx_id,)
        ) as cur:
            payment = await cur.fetchone()
            if payment:
                return payment
        async with conn.execute("""
            SELECT * FROM payments
            WHERE amount=? AND method=? AND status='pending'
            ORDER BY created_at DESC LIMIT 1
        """, (amount, method)) as cur:
            return await cur.fetchone()


async def sms_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import os
    ADMIN_ID = int(os.environ["ADMIN_ID"])

    if update.effective_user.id != ADMIN_ID:
        return

    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text(
            "❌ Format: /sms SENDER MESSAGE\n"
            "Example: /sms bKash Tk 200.00 received TrxID AB1234"
        )
        return

    sender = ctx.args[0]
    message = " ".join(ctx.args[1:])
    message = message.replace('\\n', '\n')

    logger.info(f"SMS received | sender={sender} | msg={message[:100]}")

    ALLOWED_SENDERS = ['bkash', 'nagad']
    if not any(x in sender.lower() for x in ALLOWED_SENDERS):
        await update.message.reply_text(
            f"❌ Unknown sender rejected!\n"
            f"Sender: `{sender}`\n\n"
            f"শুধু bKash ও Nagad SMS accept হবে।",
            parse_mode="Markdown"
        )
        return

    parsed = parse_sms(sender, message)

    if not parsed:
        await update.message.reply_text(
            f"⚠️ SMS parse করা যায়নি!\n\n"
            f"Sender: `{sender}`\n"
            f"Message:\n```\n{message[:300]}\n```\n\n"
            f"Manual approve করো।",
            parse_mode="Markdown"
        )
        return

    amount = parsed["amount"]
    trx_id = parsed["trx_id"]
    method = parsed["method"]

    await update.message.reply_text(
        f"✅ SMS Parsed!\n\n"
        f"💰 Amount: ৳{amount}\n"
        f"🧾 TrxID: `{trx_id}`\n"
        f"📱 Method: {method.upper()}\n\n"
        f"⏳ Matching payment খুঁজছি...",
        parse_mode="Markdown"
    )

    payment = await find_matching_payment(amount, trx_id, method)

    if not payment:
        await update.message.reply_text(
            f"❌ কোনো pending payment match হয়নি!\n\n"
            f"Amount: ৳{amount} | TrxID: `{trx_id}`\n\n"
            f"Manual check করো: /smslist",
            parse_mode="Markdown"
        )
        return

    user_id = payment["user_id"]
    plan_key = payment["plan"]
    pay_trx = payment["trx_id"]

    approved = await db.approve_payment(pay_trx)
    if not approved:
        await update.message.reply_text("❌ Already approved বা error!")
        return

    await db.create_subscription(user_id, plan_key)
    plan = db.PLANS[plan_key]

    try:
        await ctx.bot.send_message(
            user_id,
            f"🎉 Payment auto-verified!\n\n"
            f"✅ {plan['label']}\n"
            f"🎤 {plan['voice_limit']} voices\n"
            f"💰 ৳{amount} received\n\n"
            f"🎤 Voice বানান চাপো!"
        )
    except Exception as e:
        logger.error(f"Notify user error: {e}")

    await update.message.reply_text(
        f"✅ AUTO APPROVED!\n\n"
        f"👤 User: `{user_id}`\n"
        f"💳 Plan: {plan['label']}\n"
        f"💰 Amount: ৳{amount}\n"
        f"🧾 TrxID: `{pay_trx}`\n\n"
        f"User কে notification পাঠানো হয়েছে! 🎉",
        parse_mode="Markdown"
    )


async def sms_list_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    import os
    ADMIN_ID = int(os.environ["ADMIN_ID"])
    if update.effective_user.id != ADMIN_ID:
        return
    payments = await db.get_pending_payments()
    if not payments:
        await update.message.reply_text("✅ কোনো pending payment নেই!")
        return
    text = f"⏳ {len(payments)} টা Pending Payment:\n\n"
    for p in payments:
        text += (
            f"👤 {p['full_name']}\n"
            f"💳 {p['plan']} | 💰 ৳{p['amount']}\n"
            f"📱 {p['method'].upper()} | 🧾 `{p['trx_id']}`\n"
            f"📅 {p['created_at'][:16]}\n\n"
        )
    await update.message.reply_text(text[:4000], parse_mode="Markdown")
