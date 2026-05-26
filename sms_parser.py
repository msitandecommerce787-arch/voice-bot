"""
sms_parser.py — SMS Auto Payment Verification
==============================================
Android phone থেকে SMS forward হলে এই module
bKash/Nagad/Bank SMS parse করে auto approve করবে।

কিভাবে কাজ করে:
1. Android phone এ "SMS Forwarder" app install করো
2. App configure করো → Bot এ forward করবে এই format এ:
   /sms <SENDER> <MESSAGE>
3. Bot এই module দিয়ে parse করবে → auto approve করবে

SMS Forwarder App (free): 
  https://play.google.com/store/apps/details?id=com.frzinapps.smsforwarder
  অথবা "MacroDroid" app দিয়েও করা যায়।
"""

import re
import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
import database as db

logger = logging.getLogger(__name__)

# ── SMS PATTERNS ──────────────────────────────────────────────
# bKash SMS examples:
# "You have received Tk 200.00 from 01712XXXXXX. Ref 3D7ABCXYZ"
# "Tk 200.00 has been credited to your bKash account from 01712XXXXXX TrxID AB12345678"

BKASH_PATTERNS = [
    # Real bKash: "You have received Tk 1,000.00 from 01608707400. Fee Tk 0.00. Balance Tk 1,032.17. TrxID DEH4BLD432"
    r'received\s+Tk\s+([\d,]+\.?\d*).*?TrxID\s+([A-Z0-9]+)',
    # Other bKash formats
    r'Tk\s+([\d,]+\.?\d*)\s+has been credited.*?TrxID\s+([A-Z0-9]+)',
    r'(?:Tk|BDT)\s*([\d,]+\.?\d*).*?TrxID\s*:?\s*([A-Z0-9]{6,})',
]

NAGAD_PATTERNS = [
    # Real Nagad: "Money Received.\nAmount: Tk 50.00\nSender: 01866787251\nRef: N/A\nTxnID: 75FF5UT5"
    r'Amount:\s*Tk\s*([\d,]+\.?\d*).*?TxnID:\s*([A-Z0-9]+)',
    # Other Nagad formats
    r'Tk\s*([\d,]+\.?\d*).*?TxnID:\s*([A-Z0-9]+)',
    r'Amount.*?([\d,]+\.?\d*).*?TxnID\s*:?\s*([A-Z0-9]+)',
]

BANK_PATTERNS = [
    r'BDT\s*([\d,]+\.?\d*).+?(?:TxnId|TxID|TrxID)\s*:?\s*([A-Z0-9]+)',
    r'(?:credited|received)\s+(?:BDT|Tk)\s*([\d,]+\.?\d*).+?(?:TxnId|TrxID)\s*:?\s*([A-Z0-9]+)',
]


def parse_sms(sender: str, message: str) -> dict | None:
    """
    SMS parse করে amount ও trx_id বের করে।
    Returns: {"amount": float, "trx_id": str, "method": str} or None
    """
    sender_lower = sender.lower()
    message_clean = message.strip()

    # Determine payment method from sender
    if any(x in sender_lower for x in ['bkash', 'b-kash', '16247']):
        patterns = BKASH_PATTERNS
        method = 'bkash'
    elif any(x in sender_lower for x in ['nagad', 'nagad-er', '16167']):
        patterns = NAGAD_PATTERNS
        method = 'nagad'
    else:
        # Try all patterns for unknown sender
        patterns = BKASH_PATTERNS + NAGAD_PATTERNS + BANK_PATTERNS
        method = 'bank'
        # Re-check based on message content
        if 'bkash' in message_clean.lower() or 'bKash' in message_clean:
            method = 'bkash'
        elif 'nagad' in message_clean.lower():
            method = 'nagad'

    for pattern in patterns:
        match = re.search(pattern, message_clean, re.IGNORECASE)
        if match:
            try:
                amount_str = match.group(1).replace(',', '')
                amount = float(amount_str)
                trx_id = match.group(2).strip()

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
    """
    Parse করা amount/trx_id দিয়ে pending payment খোঁজে।
    Priority: trx_id match > amount match
    """
    import aiosqlite

    async with aiosqlite.connect(db.DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        # First: exact trx_id match
        async with conn.execute(
            "SELECT * FROM payments WHERE trx_id=? AND status='pending'",
            (trx_id,)
        ) as cur:
            payment = await cur.fetchone()
            if payment:
                return payment

        # Second: amount + method match (latest pending)
        async with conn.execute("""
            SELECT * FROM payments
            WHERE amount=? AND method=? AND status='pending'
            ORDER BY created_at DESC LIMIT 1
        """, (amount, method)) as cur:
            return await cur.fetchone()


# ── TELEGRAM HANDLER ──────────────────────────────────────────

async def sms_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /sms SENDER MESSAGE_TEXT
    Android SMS Forwarder app এই command পাঠাবে।
    শুধু ADMIN_ID থেকে accept করবে।
    """
    import os
    ADMIN_ID = int(os.environ["ADMIN_ID"])

    if update.effective_user.id != ADMIN_ID:
        return  # Security: শুধু admin এর phone থেকে

    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text(
            "❌ Format: /sms SENDER MESSAGE\n"
            "Example: /sms bKash Tk 200.00 received TrxID AB1234"
        )
        return

    sender = ctx.args[0]
    message = " ".join(ctx.args[1:])

    logger.info(f"SMS received from {sender}: {message[:100]}")

    # Security: শুধু bKash ও Nagad থেকে accept করো
    ALLOWED_SENDERS = ['bkash', 'nagad']
    if not any(x in sender.lower() for x in ALLOWED_SENDERS):
        await update.message.reply_text(
            f"❌ Unknown sender rejected!\n"
            f"Sender: {sender}\n\n"
            f"শুধু bKash ও Nagad SMS accept হবে।"
        )
        return

    # Parse SMS
    parsed = parse_sms(sender, message)

    if not parsed:
        await update.message.reply_text(
            f"⚠️ SMS parse করা যায়নি!\n\n"
            f"Sender: {sender}\n"
            f"Message: {message[:200]}\n\n"
            f"Manual approve করো।"
        )
        return

    amount = parsed["amount"]
    trx_id = parsed["trx_id"]
    method = parsed["method"]

    await update.message.reply_text(
        f"✅ SMS Parsed!\n\n"
        f"💰 Amount: ৳{amount}\n"
        f"🧾 TrxID: {trx_id}\n"
        f"📱 Method: {method.upper()}\n\n"
        f"⏳ Matching payment খুঁজছি..."
    )

    # Find matching payment
    payment = await find_matching_payment(amount, trx_id, method)

    if not payment:
        await update.message.reply_text(
            f"❌ কোনো pending payment match হয়নি!\n\n"
            f"Amount: ৳{amount} | TrxID: {trx_id}\n\n"
            f"Manual check করো: /smslist"
        )
        return

    # Auto approve!
    user_id = payment["user_id"]
    plan_key = payment["plan"]

    approved = await db.approve_payment(trx_id if trx_id == payment["trx_id"] else payment["trx_id"])

    if not approved:
        await update.message.reply_text("❌ Already approved বা error!")
        return

    await db.create_subscription(user_id, plan_key)
    plan = db.PLANS[plan_key]

    # Notify user
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
        f"👤 User: {user_id}\n"
        f"💳 Plan: {plan['label']}\n"
        f"💰 Amount: ৳{amount}\n"
        f"🧾 TrxID: {trx_id}\n\n"
        f"User কে notification পাঠানো হয়েছে! 🎉"
    )


async def sms_list_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Pending payments list দেখায়"""
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


# ── ANDROID SETUP GUIDE ───────────────────────────────────────

ANDROID_SETUP_GUIDE = """
📱 Android SMS Forwarder Setup Guide
=====================================

Step 1: "MacroDroid" app install করো (free)
  → Play Store: MacroDroid

Step 2: নতুন Macro বানাও:
  TRIGGER: SMS Received
    → From: bKash, Nagad, BANK (যেকোনো)
  
  ACTION: Send HTTP Request
    → URL: https://api.telegram.org/bot{BOT_TOKEN}/sendMessage
    → Method: POST
    → Body (JSON):
      {
        "chat_id": "{ADMIN_CHAT_ID}",
        "text": "/sms [sender] [message]"
      }

Step 3: MacroDroid Variables:
  [sender] = {sms_sender_address}
  [message] = {sms_message_body}

অথবা সহজ option:
  "SMS Forwarder" app → Telegram forward enable করো
  তারপর manually /sms command পাঠাও।

⚠️ Important:
  - Android phone এ bKash/Nagad SIM রাখো
  - Bot এ শুধু ADMIN এর phone থেকে /sms কাজ করবে
  - iPhone থেকে এই feature কাজ করবে না
"""
