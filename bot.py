import os
import logging
import tempfile
import google.generativeai as genai
from elevenlabs.client import ElevenLabs
from elevenlabs import VoiceSettings
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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

WAIT_TEXT, WAIT_TRX, WAIT_PLAN_SELECT = range(3)


# ── KEYBOARDS ──────────────────────────────────────────────────
def main_keyboard():
    return ReplyKeyboardMarkup([
        ["🎤 Voice বানান", "💳 Subscribe করুন"],
        ["📊 আমার Usage", "🔄 Reset"],
    ], resize_keyboard=True)


def admin_keyboard():
    return ReplyKeyboardMarkup([
        ["🎤 Voice বানান", "💳 Subscribe করুন"],
        ["📊 আমার Usage", "🔄 Reset"],
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

    keyboard = []
    row = []
    for name in VOICES:
        row.append(InlineKeyboardButton(f"🎙 {name}", callback_data=f"sv_{name}"))
        if len(row) == 2:
            keyboard.append(row); row = []
    if row: keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text("কোন voice চাও? 👇", reply_markup=InlineKeyboardMarkup(keyboard))
    return WAIT_TEXT


async def voice_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["voice"] = query.data.replace("sv_", "")
    await query.edit_message_text(f"✅ {ctx.user_data['voice']} select হয়েছে!\n\nযা বলাতে চাও সেটা লেখো (max 10 sec):")
    return WAIT_TEXT


async def receive_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Ignore keyboard button presses
    if text in ["🎤 Voice বানান", "💳 Subscribe করুন", "📊 আমার Usage", "🔄 Reset", "🛠 Admin Panel"]:
        return ConversationHandler.END

    if len(text) < 2:
        await update.message.reply_text("কিছু একটা লেখো!")
        return WAIT_TEXT
    if len(text) > 150:
        await update.message.reply_text("❌ বেশি লম্বা! max 10 sec এর মতো লেখো (~150 character)")
        return WAIT_TEXT

    can, reason = await db.can_use_voice(user_id)
    if not can:
        await update.message.reply_text("limit শেষ! নতুন plan নাও।")
        return ConversationHandler.END

    voice_name = ctx.user_data.get("voice", "Rachel")
    voice_id = VOICES[voice_name]
    msg = await update.message.reply_text("⏳ ২টা version বানাচ্ছি...")

    try:
        improved = await improve_text(text)

        audio1 = make_voice(improved, voice_id, stability=0.50, similarity=0.75, style=0.10, speed=0.72)
        audio2 = make_voice(improved, voice_id, stability=0.35, similarity=0.85, style=0.30, speed=0.60)

        tmp1 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp1.write(audio1); tmp1.close()

        tmp2 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp2.write(audio2); tmp2.close()

        await db.increment_voice_usage(user_id)
        await db.log_voice(user_id, len(text))
        sub = await db.get_active_subscription(user_id)
        remaining = sub["voice_limit"] - sub["voices_used"]

        await msg.delete()
        await update.message.reply_text(f"✨ Improved: {improved}\n🔢 Remaining: {remaining}")
        await update.message.reply_voice(voice=open(tmp1.name, "rb"), caption="🎤 Version 1 — Slow & Natural")
        await update.message.reply_voice(voice=open(tmp2.name, "rb"), caption="🎤 Version 2 — Very Slow & Emotional")

        os.unlink(tmp1.name)
        os.unlink(tmp2.name)

    except Exception as e:
        logger.error(e)
        await msg.edit_text("কিছু একটা ঠিক হয়নি, আবার try করো!")

    return ConversationHandler.END


# ── PAY ────────────────────────────────────────────────────────
async def pay_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = []
    for key, plan in db.PLANS.items():
        kb.append([InlineKeyboardButton(f"{plan['label']} | ৳{plan['price_bdt']}", callback_data=f"bp_{key}")])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text("💳 Plan select করো 👇", reply_markup=InlineKeyboardMarkup(kb))
    return WAIT_PLAN_SELECT


async def plan_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    plan_key = query.data.replace("bp_", "")
    ctx.user_data["plan"] = plan_key
    plan = db.PLANS[plan_key]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 bKash", callback_data="pm_bkash")],
        [InlineKeyboardButton("📱 Nagad", callback_data="pm_nagad")],
        [InlineKeyboardButton("💰 Binance USDT", callback_data="pm_binance")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ])
    await query.edit_message_text(
        f"✅ {plan['label']} select হয়েছে!\n💵 ৳{plan['price_bdt']} / ${plan['price_usdt']} USDT\n\nকীভাবে pay করবে?",
        reply_markup=kb
    )
    return WAIT_TRX


async def method_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    method = query.data.replace("pm_", "")
    ctx.user_data["method"] = method
    plan = db.PLANS[ctx.user_data["plan"]]

    if method == "bkash":
        txt = f"📱 **bKash নম্বর:** `{BKASH_NUMBER}`\n💰 Amount: **৳{plan['price_bdt']}**\n\nSend Money করে Transaction ID পাঠাও:"
    elif method == "nagad":
        txt = f"📱 **Nagad নম্বর:** `{NAGAD_NUMBER}`\n💰 Amount: **৳{plan['price_bdt']}**\n\nSend Money করে Transaction ID পাঠাও:"
    else:
        txt = f"💰 **Binance ID:** `{BINANCE_ID}`\n💵 Amount: **${plan['price_usdt']} USDT**\n\nTransfer করে Transaction ID পাঠাও:"

    await query.edit_message_text(txt, parse_mode="Markdown")
    return WAIT_TRX


async def receive_trx(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trx = update.message.text.strip()

    if trx in ["🎤 Voice বানান", "💳 Subscribe করুন", "📊 আমার Usage", "🔄 Reset", "🛠 Admin Panel"]:
        return ConversationHandler.END

    plan_key = ctx.user_data.get("plan")
    method = ctx.user_data.get("method")
    if not plan_key or not method:
        return ConversationHandler.END

    plan = db.PLANS[plan_key]
    await db.save_payment(user_id, method, plan["price_bdt"], plan_key, trx)

    user = update.effective_user
    # Notify admin with approve button
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 নতুন Payment!\n\n👤 {user.full_name} (@{user.username})\n🆔 `{user_id}`\n💳 {plan['label']}\n📱 {method.upper()}\n🧾 TRX: `{trx}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{trx}_{user_id}_{plan_key}")],
            [InlineKeyboardButton("❌ Reject", callback_data=f"reject_{trx}_{user_id}")],
        ])
    )
    await update.message.reply_text("✅ Done! Admin verify করলেই active হবে। সাধারণত ১-৩ ঘণ্টার মধ্যে 🙂")
    return ConversationHandler.END


# ── APPROVE/REJECT CALLBACK ────────────────────────────────────
async def payment_action_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        return

    if query.data.startswith("approve_"):
        parts = query.data.split("_")
        trx = parts[1]
        user_id = int(parts[2])
        plan_key = parts[3]

        payment = await db.approve_payment(trx)
        if not payment:
            await query.edit_message_text("❌ Already approved or not found!")
            return

        await db.create_subscription(user_id, plan_key)
        plan = db.PLANS[plan_key]

        await query.edit_message_text(
            f"✅ Approved!\n👤 User: {user_id}\n💳 {plan['label']}"
        )

        try:
            await ctx.bot.send_message(
                user_id,
                f"🎉 Subscription active!\n✅ {plan['label']}\n🎤 {plan['voice_limit']} voices\n\n🎤 Voice বানান button চাপো!"
            )
        except Exception:
            pass

    elif query.data.startswith("reject_"):
        parts = query.data.split("_")
        trx = parts[1]
        user_id = int(parts[2])

        await query.edit_message_text(f"❌ Rejected! TRX: {trx}")
        try:
            await ctx.bot.send_message(
                user_id,
                "❌ তোমার payment reject হয়েছে। সঠিক TRX ID দিয়ে আবার try করো অথবা admin এর সাথে যোগাযোগ করো।"
            )
        except Exception:
            pass


# ── ADMIN ──────────────────────────────────────────────────────
async def admin_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Not admin!")
        return
    stats = await db.get_admin_stats()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users", callback_data="adm_users")],
        [InlineKeyboardButton("⏳ Pending Payments", callback_data="adm_pending")],
    ])
    await update.message.reply_text(
        f"🛠 Admin Panel\n\n👥 Users: {stats['total_users']}\n✅ Active Subs: {stats['active_subs']}\n🎤 Voices: {stats['total_voices']}\n💰 Payments: {stats['total_payments']}\n⏳ Pending: {stats['pending_payments']}",
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
            text += f"• {u['full_name']} | {u['plan'] or 'No plan'} | ID: {u['user_id']}\n"
        await query.edit_message_text(text[:4000])

    elif query.data == "adm_pending":
        payments = await db.get_pending_payments()
        if not payments:
            await query.edit_message_text("✅ কোনো pending নেই!")
            return
        for p in payments:
            await ctx.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⏳ Pending:\n👤 {p['full_name']} (@{p['username']})\n💳 {p['plan']} | {p['method']}\n🧾 TRX: `{p['trx_id']}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{p['trx_id']}_{p['user_id']}_{p['plan']}")],
                    [InlineKeyboardButton("❌ Reject", callback_data=f"reject_{p['trx_id']}_{p['user_id']}")],
                ])
            )
        await query.edit_message_text("⏳ Pending payments পাঠানো হয়েছে!")


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


# ── RESET ──────────────────────────────────────────────────────
async def reset_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    user = update.effective_user
    kb = admin_keyboard() if user.id == ADMIN_ID else main_keyboard()
    await update.message.reply_text("🔄 Reset হয়ে গেছে!", reply_markup=kb)


# ── MESSAGE HANDLER ────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "🎤 Voice বানান":
        await voice_command(update, ctx)
    elif text == "💳 Subscribe করুন":
        await pay_command(update, ctx)
    elif text == "📊 আমার Usage":
        await mystats(update, ctx)
    elif text == "🔄 Reset":
        await reset_command(update, ctx)
    elif text == "🛠 Admin Panel" and user_id == ADMIN_ID:
        await admin_command(update, ctx)


async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("বাদ দাও তাহলে 😄")


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
            WAIT_PLAN_SELECT: [CallbackQueryHandler(plan_selected, pattern="^bp_")],
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
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(voice_conv)
    app.add_handler(pay_conv)
    app.add_handler(CallbackQueryHandler(payment_action_cb, pattern="^approve_|^reject_"))
    app.add_handler(CallbackQueryHandler(admin_cb, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^cancel$"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND &
        filters.Regex("^(📊 আমার Usage|🔄 Reset|🛠 Admin Panel)$"),
        handle_message
    ))

    logger.info("✅ Bot started!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
