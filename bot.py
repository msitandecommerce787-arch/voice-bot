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
from scheduler import start_scheduler
try:
    from invoice import generate_invoice
    HAS_INVOICE = True
except Exception:
    HAS_INVOICE = False

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
    "🐢 Very Slow": 0.70,
    "🐌 Slow": 0.80,
    "🚶 Normal": 0.90,
    "🏃 Fast": 1.0,
}

SKIP_BUTTONS = [
    "🎤 Voice বানান", "💳 Subscribe করুন", "📊 আমার Usage",
    "⚙️ Settings", "👥 Referral", "📜 History", "🛠 Admin Panel",
    "🏆 Leaderboard", "👤 Profile", "🔄 Reset"
]

WAIT_TEXT, WAIT_TRX, WAIT_PLAN_SELECT, WAIT_COUPON = range(4)


def main_keyboard():
    return ReplyKeyboardMarkup([
        ["🎤 Voice বানান", "💳 Subscribe করুন"],
        ["📊 আমার Usage", "⚙️ Settings"],
        ["👥 Referral", "📜 History"],
        ["🏆 Leaderboard", "👤 Profile"],
        ["🔄 Reset"],
    ], resize_keyboard=True)


def admin_keyboard():
    return ReplyKeyboardMarkup([
        ["🎤 Voice বানান", "💳 Subscribe করুন"],
        ["📊 আমার Usage", "⚙️ Settings"],
        ["👥 Referral", "📜 History"],
        ["🏆 Leaderboard", "👤 Profile"],
        ["🔄 Reset", "🛠 Admin Panel"],
    ], resize_keyboard=True)


def get_badge(total_voices):
    badge = db.BADGES["newcomer"]["label"]
    for key, data in db.BADGES.items():
        if total_voices >= data["voices"]:
            badge = data["label"]
    return badge


async def improve_text(text):
    try:
        r = gemini.generate_content(
            f"Improve this text for natural conversational speech. "
            f"Make it sound like a real person talking. Keep it casual. Return only improved text:\n\n{text}"
        )
        return r.text.strip()
    except Exception:
        return text


def make_voice(text, voice_id, stability=0.5, similarity=0.75, style=0.0, speed=0.75):
    try:
        voice_settings = VoiceSettings(
            stability=stability,
            similarity_boost=similarity,
            style=style,
            use_speaker_boost=True,
            speed=speed,
        )
    except Exception:
        voice_settings = VoiceSettings(
            stability=stability,
            similarity_boost=similarity,
            style=style,
            use_speaker_boost=True,
        )
    audio = eleven.generate(
        text=text,
        voice=voice_id,
        model="eleven_multilingual_v2",
        voice_settings=voice_settings,
    )
    return b"".join(audio)


# ── /start ─────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db.upsert_user(user.id, user.username, user.full_name)

    if ctx.args:
        ref_code = ctx.args[0]
        if not ref_code.startswith("RS"):
            referrer_id = await db.process_referral(ref_code, user.id)
            if referrer_id:
                try:
                    await ctx.bot.send_message(referrer_id, "🎉 তোমার referral কাজ করেছে! +3 bonus voice!")
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
        msg = "আগে subscribe করো! 💳 Subscribe করুন চাপো" if reason == "no_sub" else "limit শেষ! নতুন plan নাও 🔄"
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
    await update.message.reply_text("কোন voice চাও? ⭐ = favorite 👇", reply_markup=InlineKeyboardMarkup(keyboard))
    return WAIT_TEXT


async def voice_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["voice"] = query.data.replace("sv_", "")
    await query.edit_message_text(f"✅ {ctx.user_data['voice']} select!\n\nযা বলাতে চাও লেখো (max ~10 sec):")
    return WAIT_TEXT


async def receive_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text in SKIP_BUTTONS:
        return ConversationHandler.END

    if len(text) < 2:
        await update.message.reply_text("কিছু একটা লেখো!")
        return WAIT_TEXT
    if len(text) > 150:
        await update.message.reply_text("❌ বেশি লম্বা! max ~150 character")
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
        audio2 = make_voice(improved, voice_id, stability=0.35, similarity=0.85, style=0.30, speed=max(0.7, speed - 0.15))

        tmp1 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp1.write(audio1); tmp1.close()
        tmp2 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp2.write(audio2); tmp2.close()

        await db.increment_voice_usage(user_id)
        log_id = await db.log_voice(user_id, voice_name, len(text))
        sub = await db.get_active_subscription(user_id)
        remaining = sub["voice_limit"] - sub["voices_used"]

        await msg.delete()
        kb1 = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐1", callback_data=f"rate_{log_id}_1"),
             InlineKeyboardButton("⭐2", callback_data=f"rate_{log_id}_2"),
             InlineKeyboardButton("⭐3", callback_data=f"rate_{log_id}_3"),
             InlineKeyboardButton("⭐4", callback_data=f"rate_{log_id}_4"),
             InlineKeyboardButton("⭐5", callback_data=f"rate_{log_id}_5")],
            [InlineKeyboardButton(f"⭐ Fav", callback_data=f"fav_{voice_name}"),
             InlineKeyboardButton("📥 Download", url=f"https://t.me/{(await ctx.bot.get_me()).username}")],
        ])

        kb2 = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐1", callback_data=f"rate_{log_id}_1"),
             InlineKeyboardButton("⭐2", callback_data=f"rate_{log_id}_2"),
             InlineKeyboardButton("⭐3", callback_data=f"rate_{log_id}_3"),
             InlineKeyboardButton("⭐4", callback_data=f"rate_{log_id}_4"),
             InlineKeyboardButton("⭐5", callback_data=f"rate_{log_id}_5")],
        ])

        await update.message.reply_audio(
            audio=open(tmp1.name, "rb"),
            filename=f"voice1_{voice_name}.mp3",
            caption=f"🎤 Version 1 — Natural\n✨ {improved}\n🔢 Remaining: {remaining}",
            reply_markup=kb1
        )
        await update.message.reply_audio(
            audio=open(tmp2.name, "rb"),
            filename=f"voice2_{voice_name}.mp3",
            caption="🎤 Version 2 — Emotional",
            reply_markup=kb2
        )

        os.unlink(tmp1.name)
        os.unlink(tmp2.name)

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"VOICE ERROR: {e}")
        logger.error(f"TRACEBACK: {error_details}")
        await msg.edit_text(f"❌ Error: {str(e)[:200]}")

    return ConversationHandler.END


async def rate_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    log_id, rating = int(parts[1]), int(parts[2])
    await db.rate_voice(log_id, rating)
    await query.answer(f"{'⭐' * rating} Rating দেওয়ার জন্য ধন্যবাদ!", show_alert=True)


async def fav_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    voice_name = query.data.replace("fav_", "")
    await db.set_favorite_voice(query.from_user.id, voice_name)
    await query.answer(f"⭐ {voice_name} favorite save হয়েছে!", show_alert=True)


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
        f"⚙️ Settings\n\n🎙 Favorite: {fav or 'None'}\n⚡ Speed: {speed_label}\n\nSpeed select করো:",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def speed_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    speed = float(query.data.replace("speed_", ""))
    await db.set_user_speed(query.from_user.id, speed)
    label = next((k for k, v in SPEED_OPTIONS.items() if abs(v - speed) < 0.05), str(speed))
    await query.edit_message_text(f"✅ Speed: {label}")


# ── PROFILE ────────────────────────────────────────────────────
async def profile_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await db.get_user(user_id)
    sub = await db.get_active_subscription(user_id)
    total = await db.get_total_voices(user_id)
    badge = get_badge(total)
    fav = await db.get_favorite_voice(user_id)

    joined = user["joined_at"][:10] if user else "Unknown"
    plan = db.PLANS.get(sub["plan"], {}).get("label", "No plan") if sub else "❌ No plan"
    remaining = (sub["voice_limit"] - sub["voices_used"]) if sub else 0

    await update.message.reply_text(
        f"👤 তোমার Profile:\n\n"
        f"🏅 Badge: {badge}\n"
        f"📅 Joined: {joined}\n"
        f"🎤 Total voices: {total}\n"
        f"⭐ Favorite: {fav or 'None'}\n"
        f"✅ Plan: {plan}\n"
        f"🔢 Remaining: {remaining}"
    )


# ── HISTORY ────────────────────────────────────────────────────
async def history_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logs = await db.get_voice_history(update.effective_user.id, 5)
    if not logs:
        await update.message.reply_text("এখনো কোনো voice বানাওনি!")
        return
    text = "📜 শেষ ৫টা voice:\n\n"
    for i, log in enumerate(logs, 1):
        stars = "⭐" * log["rating"] if log["rating"] else "—"
        text += f"{i}. 🎙 {log['voice_name']} | {stars} | {log['created_at'][:16]}\n"
    await update.message.reply_text(text)


# ── LEADERBOARD ────────────────────────────────────────────────
async def leaderboard_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    leaders = await db.get_leaderboard(10)
    text = "🏆 Leaderboard:\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, l in enumerate(leaders, 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        text += f"{medal} {l['full_name']} — {l['total']} voices\n"
    await update.message.reply_text(text)


# ── REFERRAL ───────────────────────────────────────────────────
async def referral_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = await db.get_referral_code(user_id)
    bot_username = (await ctx.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={code}"
    await update.message.reply_text(
        f"👥 তোমার Referral Link:\n\n`{link}`\n\n🎁 প্রতি friend আনলে **+3 bonus voice**!",
        parse_mode="Markdown"
    )


# ── PAY ────────────────────────────────────────────────────────
async def pay_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = []
    for key, plan in db.PLANS.items():
        kb.append([InlineKeyboardButton(f"{plan['label']} | ৳{plan['price_bdt']}", callback_data=f"bp_{key}")])
    kb.append([InlineKeyboardButton("🎟 Coupon আছে?", callback_data="use_coupon")])
    kb.append([InlineKeyboardButton("🎁 Gift করো", callback_data="gift_sub")])
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
    ctx.user_data["final_price"] = final_price
    ctx.user_data["final_usdt"] = final_usdt
    discount_text = f"\n🎟 {discount}% discount applied!" if discount else ""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 bKash", callback_data="pm_bkash")],
        [InlineKeyboardButton("📱 Nagad", callback_data="pm_nagad")],
        [InlineKeyboardButton("💰 Binance USDT", callback_data="pm_binance")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ])
    await query.edit_message_text(
        f"✅ {plan['label']}{discount_text}\n💵 ৳{final_price} / ${final_usdt}\n\nPayment method:",
        reply_markup=kb
    )
    return WAIT_TRX


async def coupon_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎟 Coupon code লেখো:")
    return WAIT_COUPON


async def receive_coupon(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    if code in SKIP_BUTTONS:
        return ConversationHandler.END
    coupon = await db.use_coupon(code)
    if not coupon:
        await update.message.reply_text("❌ Invalid coupon!")
        return WAIT_COUPON
    ctx.user_data["discount"] = coupon["discount_percent"]
    await update.message.reply_text(f"✅ {coupon['discount_percent']}% discount!")
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
        txt = f"📱 **bKash:** `{BKASH_NUMBER}`\n💰 **৳{price}**\n\nTransaction ID পাঠাও:"
    elif method == "nagad":
        txt = f"📱 **Nagad:** `{NAGAD_NUMBER}`\n💰 **৳{price}**\n\nTransaction ID পাঠাও:"
    else:
        txt = f"💰 **Binance:** `{BINANCE_ID}`\n💵 **${usdt} USDT**\n\nTransaction ID পাঠাও:"
    await query.edit_message_text(txt, parse_mode="Markdown")
    return WAIT_TRX


async def receive_trx(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    trx = update.message.text.strip()
    if trx in SKIP_BUTTONS:
        return ConversationHandler.END
    plan_key = ctx.user_data.get("plan")
    method = ctx.user_data.get("method")
    if not plan_key or not method:
        return ConversationHandler.END
    plan = db.PLANS[plan_key]
    price = ctx.user_data.get("final_price", plan["price_bdt"])

    saved = await db.save_payment(user_id, method, price, plan_key, trx)
    if not saved:
        await update.message.reply_text("❌ এই TRX ID আগে ব্যবহার হয়েছে! সঠিক ID দাও।")
        return WAIT_TRX

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
            await ctx.bot.send_message(user_id, f"🎉 Subscription active!\n✅ {plan['label']}\n🎤 {plan['voice_limit']} voices\n\n🎤 Voice বানান চাপো!")
        except Exception:
            pass
        # Send invoice
        if HAS_INVOICE:
            try:
                user_info = await ctx.bot.get_chat(user_id)
                invoice_path = generate_invoice(
                    user_name=user_info.full_name,
                    plan_label=plan['label'],
                    amount=payment['amount'],
                    method=payment['method'],
                    trx_id=trx
                )
                await ctx.bot.send_document(
                    chat_id=user_id,
                    document=open(invoice_path, 'rb'),
                    filename=f"invoice_{trx}.pdf",
                    caption="📄 তোমার payment invoice!"
                )
                import os
                os.unlink(invoice_path)
            except Exception as e:
                logger.error(f"Invoice error: {e}")
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
        await update.message.reply_text("কোনো subscription নেই! 💳 Subscribe করুন চাপো")
        return
    plan = db.PLANS.get(sub["plan"], {})
    remaining = sub["voice_limit"] - sub["voices_used"]
    await update.message.reply_text(
        f"📊 তোমার Stats:\n\n✅ {plan.get('label', sub['plan'])}\n🎤 Used: {sub['voices_used']}/{sub['voice_limit']}\n🔢 Remaining: {remaining}\n📅 Expires: {sub['expires_at'][:10]}"
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
        [InlineKeyboardButton("🎟 Coupon", callback_data="adm_coupon"),
         InlineKeyboardButton("🔔 Expiry", callback_data="adm_expiry")],
        [InlineKeyboardButton("😴 Inactive", callback_data="adm_inactive"),
         InlineKeyboardButton("🤝 Reseller", callback_data="adm_reseller")],
    ])
    await update.message.reply_text(
        f"🛠 Admin Panel\n\n"
        f"👥 Users: {stats['total_users']}\n"
        f"✅ Active: {stats['active_subs']}\n"
        f"🎤 Voices: {stats['total_voices']}\n"
        f"💰 Sales: {stats['total_payments']}\n"
        f"⏳ Pending: {stats['pending_payments']}\n"
        f"💵 Revenue: ৳{stats['total_revenue']}\n"
        f"⭐ Avg Rating: {stats['avg_rating']}",
        reply_markup=kb
    )


async def admin_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return

    if query.data == "adm_users":
        users = await db.get_all_users()
        text = "👥 Users:\n\n"
        for u in users:
            ban = "🚫" if u["is_banned"] else "✅"
            text += f"{ban} {u['full_name']} | {u['plan'] or 'No plan'} | `{u['user_id']}`\n"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 Ban", callback_data="adm_ban"),
             InlineKeyboardButton("✅ Unban", callback_data="adm_unban")]
        ])
        await query.edit_message_text(text[:4000], reply_markup=kb, parse_mode="Markdown")

    elif query.data == "adm_pending":
        payments = await db.get_pending_payments()
        if not payments:
            await query.edit_message_text("✅ কোনো pending নেই!")
            return
        await query.edit_message_text(f"⏳ {len(payments)} pending পাঠাচ্ছি...")
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
        text = f"📈 Sales Report:\n\n💵 This week: ৳{report['weekly']}\n💵 This month: ৳{report['monthly']}\n\nBy Plan:\n"
        for r in report["by_plan"]:
            text += f"• {r['plan']}: {r['count']} = ৳{r['total']}\n"
        text += "\nBy Method:\n"
        for r in report["by_method"]:
            text += f"• {r['method']}: {r['count']} = ৳{r['total']}\n"
        await query.edit_message_text(text[:4000])

    elif query.data == "adm_coupon":
        await query.edit_message_text("🎟 Format: CODE DISCOUNT% MAX_USES\nExample: SAVE20 20 100")
        ctx.user_data["admin_action"] = "create_coupon"

    elif query.data == "adm_expiry":
        expiring = await db.get_expiring_soon(3)
        if not expiring:
            await query.edit_message_text("✅ কোনো expiring নেই!")
            return
        for sub in expiring:
            try:
                await ctx.bot.send_message(sub["user_id"], f"⚠️ Subscription {sub['expires_at'][:10]} তে expire হবে!\n\n💳 Renew করতে Subscribe করুন চাপো!")
            except Exception:
                pass
        await query.edit_message_text(f"✅ {len(expiring)} জন কে reminder পাঠানো হয়েছে!")

    elif query.data == "adm_inactive":
        inactive = await db.get_inactive_users(7)
        if not inactive:
            await query.edit_message_text("✅ কোনো inactive user নেই!")
            return
        for u in inactive:
            try:
                await ctx.bot.send_message(u["user_id"], "👋 অনেকদিন voice বানাওনি! এসো আবার try করো 🎤")
            except Exception:
                pass
        await query.edit_message_text(f"✅ {len(inactive)} inactive user কে reminder পাঠানো হয়েছে!")

    elif query.data == "adm_reseller":
        await query.edit_message_text("🤝 Reseller এর User ID ও commission % লেখো:\nFormat: USER_ID COMMISSION%\nExample: 123456 10")
        ctx.user_data["admin_action"] = "create_reseller"

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
    if text in SKIP_BUTTONS:
        ctx.user_data.pop("admin_action", None)
        return

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
        await update.message.reply_text(f"✅ {success}/{len(user_ids)} জন কে পাঠানো হয়েছে!")

    elif action == "create_coupon":
        try:
            parts = text.split()
            await db.create_coupon(parts[0], int(parts[1]), int(parts[2]))
            await update.message.reply_text(f"✅ Coupon: {parts[0]} | {parts[1]}% | max {parts[2]}")
        except Exception:
            await update.message.reply_text("❌ Format ঠিক নেই! Example: SAVE20 20 100")

    elif action == "create_reseller":
        try:
            parts = text.split()
            code = await db.create_reseller(int(parts[0]), int(parts[1]))
            await update.message.reply_text(f"✅ Reseller created!\nCode: {code}\nCommission: {parts[1]}%")
        except Exception:
            await update.message.reply_text("❌ Format ঠিক নেই! Example: 123456 10")

    elif action == "ban":
        try:
            await db.ban_user(int(text))
            await update.message.reply_text(f"🚫 User {text} banned!")
        except Exception:
            await update.message.reply_text("❌ Invalid ID!")

    elif action == "unban":
        try:
            await db.unban_user(int(text))
            await update.message.reply_text(f"✅ User {text} unbanned!")
        except Exception:
            await update.message.reply_text("❌ Invalid ID!")

    ctx.user_data.pop("admin_action", None)


async def menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("বাদ দাও 😄")
    elif query.data == "gift_sub":
        await query.edit_message_text("🎁 Gift feature coming soon!")


async def cancel_and_handle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await handle_buttons(update, ctx)
    return ConversationHandler.END


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
    elif text == "🏆 Leaderboard":
        await leaderboard_command(update, ctx)
    elif text == "👤 Profile":
        await profile_command(update, ctx)
    elif text == "🔄 Reset":
        ctx.user_data.clear()
        kb = admin_keyboard() if user_id == ADMIN_ID else main_keyboard()
        await update.message.reply_text("🔄 Reset!", reply_markup=kb)
    elif text == "🛠 Admin Panel" and user_id == ADMIN_ID:
        await admin_command(update, ctx)
    elif ctx.user_data.get("admin_action"):
        await admin_text_handler(update, ctx)


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
        fallbacks=[
            CallbackQueryHandler(menu_cb, pattern="^cancel$"),
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^(💳 Subscribe করুন|📊 আমার Usage|⚙️ Settings|👥 Referral|📜 History|🏆 Leaderboard|👤 Profile|🔄 Reset|🛠 Admin Panel)$"), cancel_and_handle),
        ],
        allow_reentry=True,
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
        fallbacks=[
            CallbackQueryHandler(menu_cb, pattern="^cancel$"),
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^🔄 Reset$"), menu_cb),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("mystats", mystats))
    app.add_handler(voice_conv)
    app.add_handler(pay_conv)
    app.add_handler(CallbackQueryHandler(payment_action_cb, pattern="^approve_|^reject_"))
    app.add_handler(CallbackQueryHandler(admin_cb, pattern="^adm_"))
    app.add_handler(CallbackQueryHandler(fav_cb, pattern="^fav_"))
    app.add_handler(CallbackQueryHandler(rate_cb, pattern="^rate_"))
    app.add_handler(CallbackQueryHandler(speed_cb, pattern="^speed_"))
    app.add_handler(CallbackQueryHandler(menu_cb, pattern="^cancel$|^gift_sub$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    logger.info("✅ Bot started!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

# These functions are appended - they will be registered in main()

async def birthday_command(update, ctx):
    await update.message.reply_text(
        "🎂 তোমার জন্মদিন কবে?\n\nFormat: DD-MM-YYYY\nExample: 15-03-1995"
    )
    ctx.user_data["setting_birthday"] = True


async def streak_command(update, ctx):
    user_id = update.effective_user.id
    streak = await db.get_streak(user_id)
    if not streak:
        await update.message.reply_text("এখনো কোনো streak নেই! প্রতিদিন voice বানালে streak বাড়বে 🔥")
        return
    fire = "🔥" * min(streak["current_streak"], 10)
    await update.message.reply_text(
        f"🔥 Streak:\n\n{fire}\n\n"
        f"📅 Current: {streak['current_streak']} days\n"
        f"🏆 Best: {streak['max_streak']} days\n\n"
        f"প্রতিদিন voice বানাও streak ধরে রাখো!"
    )


async def search_command(update, ctx):
    if update.effective_user.id != ADMIN_ID:
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /search name বা /search user_id")
        return
    query = " ".join(ctx.args)
    results = await db.search_user(query)
    if not results:
        await update.message.reply_text("❌ কোনো user পাওয়া যায়নি!")
        return
    text = "🔍 Search Results:\n\n"
    for u in results:
        ban = "🚫" if u["is_banned"] else "✅"
        text += f"{ban} {u['full_name']} (@{u['username'] or 'N/A'})\nID: `{u['user_id']}`\nJoined: {u['joined_at'][:10]}\n\n"
    await update.message.reply_text(text[:4000], parse_mode="Markdown")


async def givevoice_command(update, ctx):
    if update.effective_user.id != ADMIN_ID:
        return
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text("Usage: /givevoice USER_ID AMOUNT")
        return
    try:
        user_id, amount = int(ctx.args[0]), int(ctx.args[1])
        await db.give_free_voices(user_id, amount)
        await update.message.reply_text(f"✅ {user_id} কে +{amount} voices দেওয়া হয়েছে!")
        try:
            await ctx.bot.send_message(user_id, f"🎁 তোমাকে +{amount} bonus voices দেওয়া হয়েছে! 🎤")
        except Exception:
            pass
    except Exception:
        await update.message.reply_text("❌ Error! Format: /givevoice 123456 10")


async def backup_command(update, ctx):
    if update.effective_user.id != ADMIN_ID:
        return
    import shutil
    import os
    try:
        backup_path = f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.db"
        shutil.copy("bot.db", backup_path)
        await update.message.reply_document(
            document=open(backup_path, "rb"),
            filename=backup_path,
            caption="✅ Database backup!"
        )
        os.unlink(backup_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Backup failed: {e}")


async def errorlog_command(update, ctx):
    if update.effective_user.id != ADMIN_ID:
        return
    logs = await db.get_error_logs(10)
    if not logs:
        await update.message.reply_text("✅ কোনো error নেই!")
        return
    text = "🔴 Error Logs:\n\n"
    for log in logs:
        text += f"• {log['created_at'][:16]} | User: {log['user_id']}\n{log['error'][:100]}\n\n"
    await update.message.reply_text(text[:4000])


async def waitlist_command(update, ctx):
    if update.effective_user.id != ADMIN_ID:
        return
    wl = await db.get_waitlist()
    if not wl:
        await update.message.reply_text("✅ Waiting list খালি!")
        return
    text = "⏳ Waiting List:\n\n"
    for w in wl:
        text += f"• {w['full_name']} | {w['plan']} | {w['created_at'][:10]}\n"
    await update.message.reply_text(text[:4000])
