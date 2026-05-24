import asyncio
import logging
from datetime import datetime
import database as db

logger = logging.getLogger(__name__)

DAILY_QUOTES = [
    "💫 প্রতিটা দিন নতুন সুযোগ নিয়ে আসে। আজকেও সুন্দর হোক! 🌟",
    "🌸 ছোট ছোট মুহূর্তগুলোই জীবনকে সুন্দর করে। উপভোগ করো! 😊",
    "✨ তোমার কণ্ঠস্বর অনন্য। আজও সুন্দর কিছু বলো! 🎤",
    "🦋 প্রতিদিন একটু একটু করে এগিয়ে যাও। সাফল্য আসবেই! 💪",
    "🌺 ভালো কথা বলো, ভালো থাকো! আজকের দিনটা সুন্দর হোক! 🌈",
    "⭐ তোমার মনের কথাগুলো voice এ ঢেলে দাও! 🎵",
    "🎯 লক্ষ্য স্থির রাখো, সফলতা নিশ্চিত! 🏆",
]


async def send_daily_quote(app):
    while True:
        now = datetime.utcnow()
        # Send at 9 AM UTC daily
        if now.hour == 9 and now.minute == 0:
            user_ids = await db.get_all_user_ids()
            quote = DAILY_QUOTES[now.day % len(DAILY_QUOTES)]
            success = 0
            for uid in user_ids:
                try:
                    await app.bot.send_message(uid, f"🌅 Good Morning!\n\n{quote}\n\n🎤 আজকের voice বানাতে ভুলো না!")
                    success += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    pass
            logger.info(f"Daily quote sent to {success} users")
        await asyncio.sleep(60)


async def check_birthdays(app):
    while True:
        now = datetime.utcnow()
        if now.hour == 8 and now.minute == 0:
            birthday_users = await db.get_birthday_users()
            for user in birthday_users:
                try:
                    await app.bot.send_message(
                        user["user_id"],
                        f"🎂 শুভ জন্মদিন {user['full_name']}! 🎉\n\n"
                        f"🎁 তোমার জন্মদিন উপলক্ষে তোমাকে +5 bonus voice দেওয়া হয়েছে! 🎤\n"
                        f"আজকের দিনটা অনেক সুন্দর হোক! 🌟"
                    )
                    await db.give_free_voices(user["user_id"], 5)
                except Exception:
                    pass
        await asyncio.sleep(60)


async def weekly_report(app, admin_id):
    while True:
        now = datetime.utcnow()
        # Send every Monday at 10 AM UTC
        if now.weekday() == 0 and now.hour == 10 and now.minute == 0:
            report = await db.get_sales_report()
            stats = await db.get_admin_stats()
            try:
                await app.bot.send_message(
                    admin_id,
                    f"📊 Weekly Report\n\n"
                    f"👥 Total Users: {stats['total_users']}\n"
                    f"✅ Active Subs: {stats['active_subs']}\n"
                    f"🎤 Total Voices: {stats['total_voices']}\n"
                    f"💵 This Week: ৳{report['weekly']}\n"
                    f"💵 This Month: ৳{report['monthly']}\n"
                    f"⭐ Avg Rating: {stats['avg_rating']}"
                )
            except Exception:
                pass
        await asyncio.sleep(60)


async def start_scheduler(app, admin_id):
    asyncio.create_task(send_daily_quote(app))
    asyncio.create_task(check_birthdays(app))
    asyncio.create_task(weekly_report(app, admin_id))
    logger.info("✅ Scheduler started!")
