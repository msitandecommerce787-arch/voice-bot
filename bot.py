import os
import logging
import tempfile
import asyncio
import google.generativeai as genai
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters, ConversationHandler
)
import database as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN      = os.environ["BOT_TOKEN"]
ELEVENLABS_KEY = os.environ["ELEVENLABS_KEY"]
GEMINI_KEY     = os.environ["GEMINI_KEY"]
ADMIN_ID       = int(os.environ["ADMIN_ID"])
BKASH_NUMBER   = os.environ.get("BKASH_NUMBER", "01XXXXXXXXX")
NAGAD_NUMBER   = os.environ.get("NAGAD_NUMBER", "01XXXXXXXXX")
BINANCE_ID     = os.environ.get("BINANCE_ID", "YOUR_BINANCE_ID")

genai.configure(api_key=GEMINI_KEY)
gemini = genai.GenerativeModel("gemini-1.5-flash")
eleven = ElevenLabs(api_key=ELEVENLABS_KEY)

VOICES = {
    "Rachel":  "21m00Tcm4TlvDq8ikWAM",
    "Domi":    "AZnzlk1XvdvUeBnXmlld",
    "Bella":   "EXAVITQu4vr4xnSDxMaL",
    "Elli":    "MF3mGyEYCl7XYWbV9V6O",
    "Matilda": "z7HRV20pBAAeVnQFAOXX",
    "Aria":    "hNsVcO9DnD6NFXgIEQ4f",
}

SPEED_OPTIONS = {
    "🐢 Very Slow": 0.55,
    "🐌 Slow": 0.70,
    "🚶 Normal": 0.85,
    "🏃 Fast": 1.0,
}

WAIT_TEXT, WAIT_TRX, WAIT_PLAN_SELECT, WAIT_COUPON, WAIT_BROADCAST, WAIT_BAN_ID, WAIT_COUPON_CREATE = range(7)


def main_keyboard():
    return ReplyKeyboardMarkup([
        ["🎤 Voice বানান", "💳 Subscribe করুন"],
        ["📊 আমার Usage", "⚙️ Settings"],
        ["👥 Referral", "📜 History"],
        ["🔄 Reset"],
    ], resize_keyboard=True)


def admin_keyboard():
    return ReplyKeyboardMarkup([
        ["🎤 Voice বানান", "💳 Subscribe করুন"],
        ["📊 আমার Usage", "⚙️ Settings"],
        ["👥 Referral", "📜 History"],
        ["🔄 Reset"],
        ["🛠 Admin Panel"],
    ], resize_keyboard=True)


async def improve_text(text):
    try:
        r = gemini.generate_content(
            f"Improve this text for natural conversational speech. "
            f"Make it sound like a real person talking, not AI. "
            f"Keep it casual and natural. Return only the improved text:\n\n{text}"
        )
        return r.text.strip()
    except Exception:
        return text


def make_voice(text, voice_id, stability=0.5, similarity=0.75, style=0.0, speed=0.75):
    audio = eleven.generate(
        text=text,
        voice=voice_id,
        model="eleven_multilingual_v2",
        voice_settings=VoiceSettings(
            stability=stability,
            similarity_boost=similarity,
            style=style,
            use_speaker_boost=True,
            speed=speed,
        )
    )
    return b"".join(audio)


# ── /start ─────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.upsert_user(user.id, user.username, user.full_name)

    # Handle referral
    if ctx.args:
        ref_code = ctx.args[0]
        referrer_id = await db.process_referral(ref_code, user.id)
        if referrer_id:
            try:
                await ctx.bot.send_message(referrer_id, "🎉 তোমার referral কাজ করেছে! +3 bonus voice পেয়েছো!")
            except Exception:
                pass

    kb = admin_keyboard() if user.id == ADMIN_ID else main_keyboard()
    await update.message.reply_text(
        f"হ্যালো {user.first_name}! 👋\n\n🎤 Text কে real girl এর voice এ convert করি!\n\nনিচের buttons থেকে শুরু করো 👇",
        reply_markup=kb
    )


# ── VOICE ──────────────────────────────────────────────────────
async def voice_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await db.is_banned(user_id):
        await update.message.reply_text("তুমি banned 🚫")
        return ConversationHandler.END

    can, reason = await db.can_use_voice(user_id)
    if not can:
        msg = "আগে subscribe করো! 💳 Subscribe করুন button চাপো" if reason == "no_sub" else "limit শেষ! নতুন plan নাও 🔄"
        await update.message.reply_text(msg)
        return ConversationHandler.END

    fav = await db.get_favorite_voice(user_id)
    keyboard = []
    row = []
    for name in VOICES:
        label = f"⭐ {name}" if name == fav else f"🎙 {name}"
        row.append(InlineKeyboardButton(label, callback_data=f"sv_{name}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text("কোন voice চাও? ⭐ = তোমার favorite 👇", reply_markup=InlineKeyboardMarkup(keyboard))
    return WAIT_TEXT


async def voice_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["voice"] = query.data.replace("sv_", "")
    await query.edit_message_text(f"✅ {ctx.user_data['voice']} select হয়েছে!\n\nযা বলাতে চাও সেটা লেখো (max ~10 sec):")
    return WAIT_TEXT


async def receive_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    skip = ["🎤 Voice বানান", "💳 Subscribe করুন", "📊 আমার Usage", "⚙️ Settings", "👥 Referral", "📜 History", "🛠 Admin Panel", "🔄 Reset"]
    if text in skip:
        return ConversationHandler.END

    if len(text) < 2:
        await update.message.reply_text("কিছু একটা লেখো!")
        return WAIT_TEXT
    if len(text) > 150:
        await update.message.reply_text("❌ বেশি লম্বা! max ~150 character লেখো")
        return WAIT_TEXT

    can, reason = await db.can_use_voice(user_id)
    if not can:
        await update.message.reply_text("limit শেষ! নতুন plan নাও।")
        return ConversationHandler.END

    voice_name = ctx.user_data.get("voice", "Rachel")
    voice_id = VOICES[voice_name]
    speed = await db.get_user_speed(user_id)
    msg = await update.message.reply_text("⏳ ২টা version বানাচ্ছি...")

    try:
        improved = await improve_text(text)

        audio1 = make_voice(improved, voice_id, stability=0.50, similarity=0.75, style=0.10, speed=speed)
        audio2 = make_voice(improved, voice_id, stability=0.35, similarity=0.85, style=0.30, speed=max(0.45, speed - 0.15))

        tmp1 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp1.write(audio1); tmp1.close()
        tmp2 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp2.write(audio2); tmp2.close()

        await db.increment_voice_usage(user_id)
        await db.log_voice(user_id, voice_name, len(text))
        sub = await db.get_active_subscription(user_id)
        remaining = sub["voice_limit"] - sub["voices_used"]

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"⭐ Save {voice_name} as Favorite", callback_data=f"fav_{voice_name}")
        ]])

        await msg.delete()
        await update.message.reply_text(f"✨ {improved}\n🔢 Remaining: {remaining}")
        await update.message.reply_voice(voice=open(tmp1.name, "rb"), caption="🎤 Version 1 — Natural", reply_markup=kb)
        await update.message.reply_voice(voice=open(tmp2.name, "rb"), caption="🎤 Version 2 — Emotional")

        os.unlink(tmp1.name)
        os.unlink(tmp2.name)

    except Exception as e:
        logger.error(e)
        await msg.edit_text("কিছু একটা ঠিক হয়নি, আবার try করো!")

    return ConversationHandler.END


async def fav_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    voice_name = query.data.replace("fav_", "")
    await db.set_favorite_voice(query.from_user.id, voice_name)
    await query.answer(f"⭐ {voice_name} favorite হিসেবে save হয়েছে!", show_alert=True)


# ── SETTINGS ───────────────────────────────────────────────────
async def settings_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current_speed = await db.get_user_speed(user_id)
    fav = await db.get_favorite_voice(user_id)

    speed_label = next((k for k, v in SPEED_OPTIONS.items() if abs(v - current_speed) < 0.05), "Custom")

    kb = []
    for label, val in SPEED_OPTIONS.items():
        mark = "✅ " if abs(val - current_speed) < 0.05 else ""
        kb.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"speed_{val}")])

    await update.message.reply_text(
        f"⚙️ Settings\n\n🎙 Favorite Voice: {fav or 'None'}\n⚡ Speed: {speed_label}\n\nSpeed select করো:",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def speed_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    speed = float(query.data.replace("speed_", ""))
    await db.set_user_speed(query.from_user.id, speed)
    label = next((k for k, v in SPEED_OPTIONS.items() if abs(v - speed) < 0.05), str(speed))
    await query.edit_message_text(f"✅ Speed set to: {label}")


# ── HISTORY ────────────────────────────────────────────────────
async def history_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logs = await db.get_voice_history(user_id, 5)
    if not logs:
        await update.message.reply_text("এখনো কোনো voice বানাওনি!")
        return
    text = "📜 তোমার শেষ ৫টা voice:\n\n"
    for i, log in enumerate(logs, 1):
        text += f"{i}. 🎙 {log['voice_name']} | {log['text_length']} chars | {log['created_at'][:16]}\n"
    await update.message.reply_text(text)


# ── REFERRAL ───────────────────────────────────────────────────
async def referral_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = await db.get_referral_code(user_id)
    bot_username = (await ctx.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={code}"
    await update.message.reply_text(
        f"👥 তোমার Referral Link:\n\n`{link}`\n\n"
        f"🎁 প্রতি friend আনলে তুমি পাবে **+3 bonus voice**!\n"
        f"Friend কে এই link পাঠাও 👆",
        parse_mode="Markdown"
    )


# ── PAY ────────────────────────────────────────────────────────
async def pay_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = []
    for key, plan in db.PLANS.items():
        kb.append([InlineKeyboardButton(f"{plan['label']} | ৳{plan['price_bdt']}", callback_data=f"bp_{key}")])
    kb.append([InlineKeyboardButton("🎟 Coupon আছে?", callback_data="use_coupon")])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text("💳 Plan select করো 👇", reply_markup=InlineKeyboardMarkup(kb))
    return WAIT_PLAN_SELECT


async def plan_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_key = query.data.replace("bp_", "")
    ctx.user_data["plan"] = plan_key
    plan = db.PLANS[plan_key]

    discount = ctx.user_data.get("discount", 0)
    final_price = int(plan["price_bdt"] * (1 - discount / 100))
    final_usdt = round(plan["price_usdt"] * (1 - discount / 100), 2)

    discount_text = f"\n🎟 Coupon applied! {discount}% off!" if discount else ""

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 bKash", callback_data="pm_bkash")],
        [InlineKeyboardButton("📱 Nagad", callback_data="pm_nagad")],
        [InlineKeyboardButton("💰 Binance USDT", callback_data="pm_binance")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ])
    await query.edit_message_text(
        f"✅ {plan['label']} selected!{discount_text}\n💵 ৳{final_price} / ${final_usdt} USDT\n\nকীভাবে pay করবে?",
        reply_markup=kb
    )
    ctx.user_data["final_price"] = final_price
    ctx.user_data["final_usdt"] = final_usdt
    return WAIT_TRX


async def coupon_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎟 তোমার Coupon code লেখো:")
    return WAIT_COUPON


async def receive_coupon(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()

    # Allow reset/cancel during coupon entry
    skip = ["🎤 Voice বানান", "💳 Subscribe করুন", "📊 আমার Usage", "⚙️ Settings", "👥 Referral", "📜 History", "🛠 Admin Panel", "🔄 Reset"]
    if code in skip:
        ctx.user_data.clear()
        user = update.effective_user
        from telegram import ReplyKeyboardMarkup
        kb = admin_keyboard() if user.id == ADMIN_ID else main_keyboard()
        await update.message.reply_text("🔄 Reset হয়ে গেছে!", reply_markup=kb)
        return ConversationHandler.END

    coupon = await db.use_coupon(code)
    if not coupon:
        await update.message.reply_text(
            "❌ Invalid বা expired coupon!\n\n"
            "আবার try করো অথবা /reset লেখো বাতিল করতে।"
        )
        return WAIT_COUPON
    ctx.user_data["discount"] = coupon["discount_percent"]
    await update.message.reply_text(f"✅ Coupon applied! {coupon['discount_percent']}% discount পেয়েছো!")
    await pay_command(update, ctx)
    return WAIT_PLAN_SELECT


async def method_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("pm_", "")
    ctx.user_data["method"] = method
    plan = db.PLANS[ctx.user_data["plan"]]
    price = ctx.user_data.get("final_price", plan["price_bdt"])
    usdt = ctx.user_data.get("final_usdt", plan["price_usdt"])

    if method == "bkash":
        txt = f"📱 **bKash:** `{BKASH_NUMBER}`\n💰 Amount: **৳{price}**\n\nTransaction ID পাঠাও:"
    elif method == "nagad":
        txt = f"📱 **Nagad:** `{NAGAD_NUMBER}`\n💰 Amount: **৳{price}**\n\nTransaction ID পাঠাও:"
    else:
        txt = f"💰 **Binance:** `{BINANCE_ID}`\n💵 Amount: **${usdt} USDT**\n\nTransaction ID পাঠাও:"

    await query.edit_message_text(txt, parse_mode="Markdown")
    return WAIT_TRX


async def receive_trx(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trx = update.message.text.strip()

    skip = ["🎤 Voice বানান", "💳 Subscribe করুন", "📊 আমার Usage", "⚙️ Settings", "👥 Referral", "📜 History", "🛠 Admin Panel", "🔄 Reset"]
    if trx in skip:
        return ConversationHandler.END

    plan_key = ctx.user_data.get("plan")
    method = ctx.user_data.get("method")
    if not plan_key or not method:
        return ConversationHandler.END

    plan = db.PLANS[plan_key]
    price = ctx.user_data.get("final_price", plan["price_bdt"])
    await db.save_payment(user_id, method, price, plan_key, trx)

    user = update.effective_user
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 নতুন Payment!\n\n👤 {user.full_name} (@{user.username})\n🆔 `{user_id}`\n💳 {plan['label']}\n📱 {method.upper()}\n💰 ৳{price}\n🧾 TRX: `{trx}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{trx}_{user_id}_{plan_key}")],
            [InlineKeyboardButton("❌ Reject", callback_data=f"reject_{trx}_{user_id}")],
        ])
    )
    await update.message.reply_text("✅ Done! Admin verify করলেই active হবে 🙂")
    return ConversationHandler.END


# ── PAYMENT ACTION ─────────────────────────────────────────────
async def payment_action_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return

    if query.data.startswith("approve_"):
        parts = query.data.split("_")
        trx, user_id, plan_key = parts[1], int(parts[2]), parts[3]
        payment = await db.approve_payment(trx)
        if not payment:
            await query.edit_message_text("❌ Already approved!")
            return
        await db.create_subscription(user_id, plan_key)
        plan = db.PLANS[plan_key]
        await query.edit_message_text(f"✅ Approved!\n👤 {user_id}\n💳 {plan['label']}")
        try:
            await ctx.bot.send_message(user_id, f"🎉 Subscription active!\n✅ {plan['label']}\n🎤 {plan['voice_limit']} voices\n\n🎤 Voice বানান button চাপো!")
        except Exception:
            pass

    elif query.data.startswith("reject_"):
        parts = query.data.split("_")
        trx, user_id = parts[1], int(parts[2])
        await query.edit_message_text(f"❌ Rejected! TRX: {trx}")
        try:
            await ctx.bot.send_message(user_id, "❌ Payment reject হয়েছে। Admin এর সাথে যোগাযোগ করো।")
        except Exception:
            pass


# ── MYSTATS ────────────────────────────────────────────────────
async def mystats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sub = await db.get_active_subscription(update.effective_user.id)
    if not sub:
        await update.message.reply_text("কোনো subscription নেই! 💳 Subscribe করুন button চাপো")
        return
    plan = db.PLANS.get(sub["plan"], {})
    remaining = sub["voice_limit"] - sub["voices_used"]
    await update.message.reply_text(
        f"📊 তোমার Stats:\n\n✅ Plan: {plan.get('label', sub['plan'])}\n🎤 Used: {sub['voices_used']}/{sub['voice_limit']}\n🔢 Remaining: {remaining}\n📅 Expires: {sub['expires_at'][:10]}"
    )


# ── ADMIN ──────────────────────────────────────────────────────
async def admin_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    stats = await db.get_admin_stats()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users", callback_data="adm_users"),
         InlineKeyboardButton("⏳ Pending", callback_data="adm_pending")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
         InlineKeyboardButton("📈 Sales", callback_data="adm_sales")],
        [InlineKeyboardButton("🎟 Create Coupon", callback_data="adm_coupon"),
         InlineKeyboardButton("🔔 Expiry Alert", callback_data="adm_expiry")],
    ])
    await update.message.reply_text(
        f"🛠 Admin Panel\n\n"
        f"👥 Users: {stats['total_users']}\n"
        f"✅ Active Subs: {stats['active_subs']}\n"
        f"🎤 Voices: {stats['total_voices']}\n"
        f"💰 Payments: {stats['total_payments']}\n"
        f"⏳ Pending: {stats['pending_payments']}\n"
        f"💵 Revenue: ৳{stats['total_revenue']}",
        reply_markup=kb
    )


async def admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return

    if query.data == "adm_users":
        users = await db.get_all_users()
        text = "👥 Recent Users:\n\n"
        for u in users:
            ban = "🚫" if u["is_banned"] else "✅"
            text += f"{ban} {u['full_name']} | {u['plan'] or 'No plan'} | `{u['user_id']}`\n"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban"),
             InlineKeyboardButton("✅ Unban User", callback_data="adm_unban")]
        ])
        await query.edit_message_text(text[:4000], reply_markup=kb, parse_mode="Markdown")

    elif query.data == "adm_pending":
        payments = await db.get_pending_payments()
        if not payments:
            await query.edit_message_text("✅ কোনো pending নেই!")
            return
        await query.edit_message_text(f"⏳ {len(payments)} pending payments পাঠাচ্ছি...")
        for p in payments:
            await ctx.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⏳ {p['full_name']} | {p['plan']} | {p['method']}\nTRX: `{p['trx_id']}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{p['trx_id']}_{p['user_id']}_{p['plan']}")],
                    [InlineKeyboardButton("❌ Reject", callback_data=f"reject_{p['trx_id']}_{p['user_id']}")],
                ])
            )

    elif query.data == "adm_broadcast":
        await query.edit_message_text("📢 Broadcast message লেখো:")
        ctx.user_data["admin_action"] = "broadcast"

    elif query.data == "adm_sales":
        report = await db.get_sales_report()
        text = "📈 Sales Report:\n\n"
        text += f"💵 This month: ৳{report['monthly']}\n\n"
        text += "By Plan:\n"
        for r in report["by_plan"]:
            text += f"• {r['plan']}: {r['count']} sales = ৳{r['total']}\n"
        text += "\nBy Method:\n"
        for r in report["by_method"]:
            text += f"• {r['method']}: {r['count']} = ৳{r['total']}\n"
        await query.edit_message_text(text[:4000])

    elif query.data == "adm_coupon":
        await query.edit_message_text("🎟 Coupon info লেখো:\nFormat: CODE DISCOUNT% MAX_USES\nExample: SAVE20 20 100")
        ctx.user_data["admin_action"] = "create_coupon"

    elif query.data == "adm_expiry":
        expiring = await db.get_expiring_soon(3)
        if not expiring:
            await query.edit_message_text("✅ কোনো expiring subscription নেই!")
            return
        for sub in expiring:
            try:
                await ctx.bot.send_message(
                    sub["user_id"],
                    f"⚠️ তোমার subscription {sub['expires_at'][:10]} তারিখে expire হবে!\n\n💳 Renew করতে Subscribe করুন button চাপো!"
                )
            except Exception:
                pass
        await query.edit_message_text(f"✅ {len(expiring)} জন user কে reminder পাঠানো হয়েছে!")

    elif query.data == "adm_ban":
        await query.edit_message_text("🚫 Ban করতে User ID লেখো:")
        ctx.user_data["admin_action"] = "ban"

    elif query.data == "adm_unban":
        await query.edit_message_text("✅ Unban করতে User ID লেখো:")
        ctx.user_data["admin_action"] = "unban"


async def admin_text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    action = ctx.user_data.get("admin_action")
    if not action:
        return

    text = update.message.text.strip()

    if action == "broadcast":
        user_ids = await db.get_all_user_ids()
        success = 0
        for uid in user_ids:
            try:
                await ctx.bot.send_message(uid, f"📢 {text}")
                success += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
        await update.message.reply_text(f"✅ {success}/{len(user_ids)} জন কে message পাঠানো হয়েছে!")

    elif action == "create_coupon":
        try:
            parts = text.split()
            code, discount, max_uses = parts[0], int(parts[1]), int(parts[2])
            await db.create_coupon(code, discount, max_uses)
            await update.message.reply_text(f"✅ Coupon created!\nCode: {code}\nDiscount: {discount}%\nMax uses: {max_uses}")
        except Exception:
            await update.message.reply_text("❌ Format ঠিক নেই! Example: SAVE20 20 100")

    elif action == "ban":
        try:
            await db.ban_user(int(text))
            await update.message.reply_text(f"🚫 User {text} banned!")
        except Exception:
            await update.message.reply_text("❌ Invalid user ID!")

    elif action == "unban":
        try:
            await db.unban_user(int(text))
            await update.message.reply_text(f"✅ User {text} unbanned!")
        except Exception:
            await update.message.reply_text("❌ Invalid user ID!")

    ctx.user_data.pop("admin_action", None)


async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("বাদ দাও তাহলে 😄")


async def handle_buttons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    if text == "📊 আমার Usage":
        await mystats(update, ctx)
    elif text == "⚙️ Settings":
        await settings_command(update, ctx)
    elif text == "👥 Referral":
        await referral_command(update, ctx)
    elif text == "📜 History":
        await history_command(update, ctx)
    elif text == "🛠 Admin Panel" and user_id == ADMIN_ID:
        await admin_command(update, ctx)
    elif text == "🔄 Reset":
        ctx.user_data.clear()
        user = update.effective_user
        kb = admin_keyboard() if user.id == ADMIN_ID else main_keyboard()
        await update.message.reply_text("🔄 Reset হয়ে গেছে!", reply_markup=kb)
    elif ctx.user_data.get("admin_action"):
        await admin_text_handler(update, ctx)


async def reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    user = update.effective_user
    kb = admin_keyboard() if user.id == ADMIN_ID else main_keyboard()
    await update.message.reply_text("🔄 Reset হয়ে গেছে!", reply_markup=kb)


async def post_init(app):
    await db.init_db()


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    voice_conv = ConversationHandler(
        entry_points=[
            CommandHandler("voice", voice_command),
            MessageHandler(filters.Regex("^🎤 Voice বানান$"), voice_command),
        ],
        states={
            WAIT_TEXT: [
                CallbackQueryHandler(voice_selected, pattern="^sv_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text),
            ],
        },
        fallbacks=[CallbackQueryHandler(menu_cb, pattern="^cancel$")],
    )

    pay_conv = ConversationHandler(
        entry_points=[
            CommandHandler("pay", pay_command),
            MessageHandler(filters.Regex("^💳 Subscribe করুন$"), pay_command),
        ],
        states={
            WAIT_PLAN_SELECT: [
                CallbackQueryHandler(plan_selected, pattern="^bp_"),
                CallbackQueryHandler(coupon_prompt, pattern="^use_coupon$"),
            ],
            WAIT_COUPON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_coupon),
            ],
            WAIT_TRX: [
                CallbackQueryHandler(method_selected, pattern="^pm_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_trx),
            ],
        },
        fallbacks=[CallbackQueryHandler(menu_cb, pattern="^cancel$")],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("mystats", mystats))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(voice_conv)
    app.add_handler(pay_conv)
    app.add_handler(CallbackQueryHandler(payment_action_cb, pattern="^approve_|^reject_"))
    app.add_handler(CallbackQueryHandler(admin_cb, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(fav_cb, pattern="^fav_"))
    app.add_handler(CallbackQueryHandler(speed_cb, pattern="^speed_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^cancel$"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_buttons
    ))

    logger.info("✅ Bot started!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
