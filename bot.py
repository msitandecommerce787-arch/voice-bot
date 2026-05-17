import os
import logging
import tempfile
import google.generativeai as genai
from elevenlabs.client import ElevenLabs
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
    "Domi":   "AZnzlk1XvdvUeBnXmlld",
    "Bella":  "EXAVITQu4vr4xnSDxMaL",
    "Elli":   "MF3mGyEYCl7XYWbV9V6O",
}

WAIT_TEXT, WAIT_TRX, WAIT_PLAN_SELECT = range(3)


async def improve_text(text):
    try:
        r = gemini.generate_content(
            f"Improve this text for natural speech. Return only improved text:\n\n{text}"
        )
        return r.text.strip()
    except Exception:
        return text


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.upsert_user(user.id, user.username, user.full_name)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎤 Voice বানান", callback_data="menu_voice")],
        [InlineKeyboardButton("💳 Subscribe করুন", callback_data="menu_pay")],
        [InlineKeyboardButton("📊 আমার Usage", callback_data="menu_stats")],
    ])
    await update.message.reply_text(
        f"👋 স্বাগতম {user.first_name}!\n\n🎤 Text কে Girls Voice এ convert করুন!\n\nনিচের menu থেকে শুরু করুন 👇",
        reply_markup=kb
    )


async def voice_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await db.is_banned(user_id):
        await update.message.reply_text("❌ আপনি banned।")
        return ConversationHandler.END

    can, reason = await db.can_use_voice(user_id)
    if not can:
        msg = "❌ Subscription নেই! /pay দিয়ে subscribe করুন।" if reason == "no_sub" else "❌ Voice limit শেষ! /pay দিয়ে renew করুন।"
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
    await update.message.reply_text("🎤 Voice select করুন:", reply_markup=InlineKeyboardMarkup(keyboard))
    return WAIT_TEXT


async def voice_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["voice"] = query.data.replace("sv_", "")
    await query.edit_message_text(f"✅ {ctx.user_data['voice']} selected!\n\nএখন text লিখুন:")
    return WAIT_TEXT


async def receive_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if len(text) < 2:
        await update.message.reply_text("❌ কিছু লিখুন!")
        return WAIT_TEXT
    if len(text) > 500:
        await update.message.reply_text("❌ সর্বোচ্চ 500 character!")
        return WAIT_TEXT

    can, reason = await db.can_use_voice(user_id)
    if not can:
        await update.message.reply_text("❌ Limit শেষ! /pay দিয়ে subscribe করুন।")
        return ConversationHandler.END

    voice_name = ctx.user_data.get("voice", "Rachel")
    voice_id = VOICES[voice_name]
    msg = await update.message.reply_text("⏳ Voice তৈরি হচ্ছে...")

    try:
        improved = await improve_text(text)
        audio = eleven.generate(text=improved, voice=voice_id, model="eleven_multilingual_v2")
        audio_bytes = b"".join(audio)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name

        await db.increment_voice_usage(user_id)
        await db.log_voice(user_id, len(text))
        sub = await db.get_active_subscription(user_id)
        remaining = sub["voice_limit"] - sub["voices_used"]

        await msg.delete()
        await update.message.reply_voice(
            voice=open(tmp, "rb"),
            caption=f"🎤 {voice_name}\n📝 Original: {text}\n✨ Improved: {improved}\n🔢 Remaining: {remaining}"
        )
        os.unlink(tmp)
    except Exception as e:
        logger.error(e)
        await msg.edit_text("❌ Error! আবার চেষ্টা করুন।")

    return ConversationHandler.END


async def pay_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = []
    for key, plan in db.PLANS.items():
        kb.append([InlineKeyboardButton(f"{plan['label']} | ৳{plan['price_bdt']}", callback_data=f"bp_{key}")])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text("💳 Plan select করুন:", reply_markup=InlineKeyboardMarkup(kb))
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
        f"✅ {plan['label']} selected!\n💵 ৳{plan['price_bdt']} / ${plan['price_usdt']} USDT\n\nPayment method বেছে নিন:",
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
        txt = f"📱 **bKash:**\nNumber: `{BKASH_NUMBER}`\nAmount: **৳{plan['price_bdt']}**\n\nTransaction ID পাঠান:"
    elif method == "nagad":
        txt = f"📱 **Nagad:**\nNumber: `{NAGAD_NUMBER}`\nAmount: **৳{plan['price_bdt']}**\n\nTransaction ID পাঠান:"
    else:
        txt = f"💰 **Binance:**\nID: `{BINANCE_ID}`\nAmount: **${plan['price_usdt']} USDT**\n\nTransaction ID পাঠান:"

    await query.edit_message_text(txt, parse_mode="Markdown")
    return WAIT_TRX


async def receive_trx(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trx = update.message.text.strip()
    plan_key = ctx.user_data.get("plan")
    method = ctx.user_data.get("method")
    plan = db.PLANS[plan_key]

    await db.save_payment(user_id, method, plan["price_bdt"], plan_key, trx)

    user = update.effective_user
    await ctx.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🔔 নতুন Payment!\n\n👤 {user.full_name} (@{user.username})\n🆔 `{user_id}`\n💳 {plan['label']}\n📱 {method.upper()}\n🧾 TRX: `{trx}`\n\nApprove: `/approve {trx}`",
        parse_mode="Markdown"
    )
    await update.message.reply_text("✅ Payment request পাঠানো হয়েছে!\nAdmin verify করলে আপনার subscription active হবে।")
    return ConversationHandler.END


async def approve_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /approve TRX_ID")
        return
    payment = await db.approve_payment(ctx.args[0])
    if not payment:
        await update.message.reply_text("❌ Payment পাওয়া যায়নি!")
        return
    await db.create_subscription(payment["user_id"], payment["plan"])
    plan = db.PLANS[payment["plan"]]
    await update.message.reply_text(f"✅ Approved! {plan['label']} active করা হয়েছে।")
    try:
        await ctx.bot.send_message(
            payment["user_id"],
            f"🎉 Subscription Active!\n✅ {plan['label']}\n🎤 {plan['voice_limit']} voices/month\n\n/voice দিয়ে শুরু করুন!"
        )
    except Exception:
        pass


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
        text = "⏳ Pending:\n\n"
        for p in payments:
            text += f"• {p['full_name']} | {p['plan']} | {p['method']}\n  TRX: {p['trx_id']}\n  /approve {p['trx_id']}\n\n"
        await query.edit_message_text(text[:4000])


async def mystats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sub = await db.get_active_subscription(update.effective_user.id)
    if not sub:
        await update.message.reply_text("❌ Subscription নেই! /pay দিয়ে subscribe করুন।")
        return
    plan = db.PLANS.get(sub["plan"], {})
    remaining = sub["voice_limit"] - sub["voices_used"]
    await update.message.reply_text(
        f"📊 আপনার Stats:\n\n✅ Plan: {plan.get('label', sub['plan'])}\n🎤 Used: {sub['voices_used']}/{sub['voice_limit']}\n🔢 Remaining: {remaining}\n📅 Expires: {sub['expires_at'][:10]}"
    )


async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "menu_voice":
        await query.message.reply_text("👉 /voice লিখুন!")
    elif query.data == "menu_pay":
        await query.message.reply_text("👉 /pay লিখুন!")
    elif query.data == "menu_stats":
        await query.message.reply_text("👉 /mystats লিখুন!")
    elif query.data == "cancel":
        await query.edit_message_text("❌ Cancelled.")


async def post_init(app):
    await db.init_db()


def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    voice_conv = ConversationHandler(
        entry_points=[CommandHandler("voice", voice_command)],
        states={
            WAIT_TEXT: [
                CallbackQueryHandler(voice_selected, pattern="^sv_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_text),
            ],
        },
        fallbacks=[CallbackQueryHandler(menu_cb, pattern="^cancel$")],
    )

    pay_conv = ConversationHandler(
        entry_points=[CommandHandler("pay", pay_command)],
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
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("mystats", mystats))
    app.add_handler(voice_conv)
    app.add_handler(pay_conv)
    app.add_handler(CallbackQueryHandler(admin_cb, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^menu_|^cancel$"))

    logger.info("✅ Bot started!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
