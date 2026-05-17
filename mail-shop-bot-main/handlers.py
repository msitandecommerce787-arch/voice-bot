import uuid
import io
import csv
import datetime
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_IDS, BKASH_NUMBER, NAGAD_NUMBER, DEPOSIT_BONUSES
from database import (
    get_user, update_user, get_products, get_variant,
    add_stock, pop_stock, add_pending_deposit,
    clear_pending_deposit, add_order, get_all_users, PRODUCTS
)
from keyboards import (
    main_menu_keyboard, products_keyboard, variants_keyboard,
    purchase_mode_keyboard, deposit_keyboard, back_keyboard,
    admin_keyboard, admin_products_keyboard, admin_variants_keyboard,
    persistent_reply_keyboard
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    db_user = await get_user(uid)
    await update_user(uid, {"name": user.full_name, "username": user.username or ""})
    await update.message.reply_text("✅ Bot চালু হয়েছে!", reply_markup=persistent_reply_keyboard())
    await update.message.reply_text(
        f"👋 *স্বাগতম {user.first_name}!*\n\n🏪 *Mail Shop*\n💰 ব্যালেন্স: *{db_user['balance']:.2f} TK*",
        reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ আপনার অ্যাক্সেস নেই!")
        return
    await update.message.reply_text("🔧 *Admin Panel*", reply_markup=admin_keyboard(), parse_mode="Markdown")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    uid = str(user.id)

    if data == "main_menu":
        db_user = await get_user(uid)
        await query.edit_message_text(
            f"🏪 *Mail Shop* মেনু\n💰 ব্যালেন্স: *{db_user['balance']:.2f} TK*",
            reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )
    elif data == "shop":
        products = await get_products()
        await query.edit_message_text("🛍️ *একটি পণ্য বেছে নিন:*", reply_markup=products_keyboard(products), parse_mode="Markdown")
    elif data.startswith("product_"):
        product_key = data.replace("product_", "")
        products = await get_products()
        if product_key not in products:
            await query.edit_message_text("❌ পণ্য পাওয়া যায়নি।", reply_markup=back_keyboard("shop"))
            return
        product = products[product_key]
        await query.edit_message_text(
            f"🔖 *{product['name']}* - ভ্যারিয়েন্ট বেছে নিন:",
            reply_markup=variants_keyboard(product_key, product["variants"]), parse_mode="Markdown"
        )
    elif data.startswith("variant_"):
        parts = data.split("_", 2)
        product_key = parts[1]
        variant_key = parts[2]
        variant = await get_variant(product_key, variant_key)
        stock_count = len(variant["stock"])
        await query.edit_message_text(
            f"📦 *{variant['name']}*\n💰 মূল্য: *{variant['price']} TK*\n📊 স্টক: *{stock_count}*\n\nকিভাবে কিনতে চান?",
            reply_markup=purchase_mode_keyboard(product_key, variant_key), parse_mode="Markdown"
        )
    elif data.startswith("buy_single_"):
        _, _, product_key, variant_key = data.split("_", 3)
        await _process_purchase(query, uid, product_key, variant_key, 1)
    elif data.startswith("buy_bulk_"):
        _, _, product_key, variant_key = data.split("_", 3)
        context.user_data["bulk_buy"] = {"product_key": product_key, "variant_key": variant_key}
        await query.edit_message_text("📦 *বাল্ক ক্রয়*\nকতটি কিনতে চান? (1-1000)\n\nসংখ্যাটি টাইপ করুন:", parse_mode="Markdown")
    elif data == "profile":
        db_user = await get_user(uid)
        await query.edit_message_text(
            f"👤 *আপনার প্রোফাইল*\n\n📛 নাম: {db_user.get('name','N/A')}\n🆔 User ID: {uid}\n"
            f"👤 Username: @{db_user.get('username','N/A')}\n💰 ব্যালেন্স: *{db_user['balance']:.2f} TK*\n"
            f"📥 আজ জমা: {db_user['deposited_today']:.2f} TK\n💸 আজ খরচ: {db_user['spent_today']:.2f} TK\n"
            f"📊 মোট খরচ: {db_user['total_spent']:.2f} TK",
            reply_markup=back_keyboard(), parse_mode="Markdown"
        )
    elif data == "deposit":
        bonus_text = "\n".join([f"💰 {b['min']}-{b['max']} TK জমা দিলে ফ্রি {b['bonus']} TK" for b in DEPOSIT_BONUSES])
        await query.edit_message_text(
            f"💳 *ডিপোজিট করুন*\n\n🎁 *বোনাস:*\n{bonus_text}\n\n💳 Bkash/Nagad: `{BKASH_NUMBER}`\n\n"
            f"➤ টাকা পাঠান → Transaction ID পাঠান → Amount লিখুন",
            reply_markup=deposit_keyboard(), parse_mode="Markdown"
        )
    elif data == "send_txn":
        context.user_data["awaiting"] = "txn_id"
        await query.edit_message_text("📤 *Transaction ID পাঠান:*", parse_mode="Markdown")
    elif data == "support":
        await query.edit_message_text(
            "📞 *সাপোর্ট*\n\nযেকোনো সমস্যায়:\n@joysarker787\n@smith78786",
            reply_markup=back_keyboard(), parse_mode="Markdown"
        )
    elif data == "refer":
        ref_link = f"https://t.me/{context.bot.username}?start=ref_{uid}"
        await query.edit_message_text(
            f"🎁 *রেফারেল লিংক:*\n`{ref_link}`",
            reply_markup=back_keyboard(), parse_mode="Markdown"
        )
    elif data == "admin_panel":
        if user.id not in ADMIN_IDS:
            await query.answer("❌ অ্যাক্সেস নেই!", show_alert=True)
            return
        await query.edit_message_text("🔧 *Admin Panel*", reply_markup=admin_keyboard(), parse_mode="Markdown")
    elif data == "admin_add_stock":
        if user.id not in ADMIN_IDS: return
        products = await get_products()
        await query.edit_message_text("📦 *পণ্য বেছে নিন:*", reply_markup=admin_products_keyboard(products, "adstock_prod"), parse_mode="Markdown")
    elif data.startswith("adstock_prod_"):
        if user.id not in ADMIN_IDS: return
        product_key = data.replace("adstock_prod_", "")
        products = await get_products()
        await query.edit_message_text("📦 *ভ্যারিয়েন্ট বেছে নিন:*", reply_markup=admin_variants_keyboard(product_key, products[product_key]["variants"], "adstock_var"), parse_mode="Markdown")
    elif data.startswith("adstock_var_"):
        if user.id not in ADMIN_IDS: return
        parts = data.split("_", 3)
        context.user_data["admin_add_stock"] = {"product_key": parts[2], "variant_key": parts[3]}
        context.user_data["awaiting"] = "admin_stock_items"
        await query.edit_message_text("📝 *আইটেম পাঠান* (প্রতি লাইনে একটি):\n\nউদাহরণ:\nemail@ex.com:pass123", parse_mode="Markdown")
    elif data == "admin_approve":
        if user.id not in ADMIN_IDS: return
        context.user_data["awaiting"] = "admin_approve_deposit"
        await query.edit_message_text("✅ *ফরম্যাট:* `user_id amount`\nউদাহরণ: `123456789 500`", parse_mode="Markdown")
    elif data == "admin_stats":
        if user.id not in ADMIN_IDS: return
        users = await get_all_users()
        total_balance = sum(u["balance"] for u in users.values())
        products = await get_products()
        stock_info = "".join([f"• {v['name']}: {len(v['stock'])}\n" for p in products.values() for v in p["variants"].values()])
        await query.edit_message_text(
            f"📊 *Statistics*\n\n👥 ইউজার: {len(users)}\n💰 মোট ব্যালেন্স: {total_balance:.2f} TK\n\n📦 *স্টক:*\n{stock_info}",
            reply_markup=back_keyboard("admin_panel"), parse_mode="Markdown"
        )
    elif data == "admin_broadcast":
        if user.id not in ADMIN_IDS: return
        context.user_data["awaiting"] = "admin_broadcast"
        await query.edit_message_text("📢 সকলকে পাঠাতে চান এমন মেসেজ লিখুন:", parse_mode="Markdown")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    text = update.message.text.strip()
    awaiting = context.user_data.get("awaiting")

    if text == "🔄 Restart":
        db_user = await get_user(uid)
        await update.message.reply_text(
            f"🏪 *Mail Shop* মেনু\n💰 ব্যালেন্স: *{db_user['balance']:.2f} TK*",
            reply_markup=main_menu_keyboard(), parse_mode="Markdown"
        )
        return
    if text == "🛍️ Shop Now":
        products = await get_products()
        await update.message.reply_text("🛍️ *পণ্য বেছে নিন:*", reply_markup=products_keyboard(products), parse_mode="Markdown")
        return
    if text == "💳 Deposit":
        bonus_text = "\n".join([f"💰 {b['min']}-{b['max']} TK → ফ্রি {b['bonus']} TK" for b in DEPOSIT_BONUSES])
        await update.message.reply_text(
            f"💳 *ডিপোজিট*\n\n🎁 *বোনাস:*\n{bonus_text}\n\n💳 Bkash/Nagad: `{BKASH_NUMBER}`",
            reply_markup=deposit_keyboard(), parse_mode="Markdown"
        )
        return
    if text == "👤 Profile":
        db_user = await get_user(uid)
        await update.message.reply_text(
            f"👤 *প্রোফাইল*\n\n🆔 ID: {uid}\n💰 ব্যালেন্স: *{db_user['balance']:.2f} TK*\n"
            f"📥 আজ জমা: {db_user['deposited_today']:.2f} TK\n💸 মোট খরচ: {db_user['total_spent']:.2f} TK",
            reply_markup=back_keyboard(), parse_mode="Markdown"
        )
        return
    if text == "🎁 Refer":
        ref_link = f"https://t.me/{context.bot.username}?start=ref_{uid}"
        await update.message.reply_text(f"🎁 *রেফারেল লিংক:*\n`{ref_link}`", reply_markup=back_keyboard(), parse_mode="Markdown")
        return
    if text == "📞 Support":
        await update.message.reply_text("📞 *সাপোর্ট:*\n@joysarker787\n@smith78786", reply_markup=back_keyboard(), parse_mode="Markdown")
        return

    if "bulk_buy" in context.user_data and awaiting != "txn_id":
        try:
            qty = int(text)
            if not (1 <= qty <= 1000): raise ValueError
            bulk = context.user_data.pop("bulk_buy")
            await _process_purchase_msg(update, context, uid, bulk["product_key"], bulk["variant_key"], qty)
        except ValueError:
            await update.message.reply_text("❌ সঠিক সংখ্যা দিন (1-1000)!")
        return

    if awaiting == "txn_id":
        context.user_data["txn_id"] = text
        context.user_data["awaiting"] = "txn_amount"
        await update.message.reply_text("💰 কত টাকা পাঠিয়েছেন?")
        return

    if awaiting == "txn_amount":
        try:
            amount = float(text)
            txn_id = context.user_data.pop("txn_id", "N/A")
            context.user_data.pop("awaiting", None)
            await add_pending_deposit(uid, amount)
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(admin_id,
                        f"💳 *নতুন ডিপোজিট*\n👤 {user.full_name} (@{user.username})\n🆔 {uid}\n"
                        f"💰 {amount} TK\n🧾 `{txn_id}`\n\nঅনুমোদন: `/approve {uid} {amount}`",
                        parse_mode="Markdown")
                except: pass
            db_user = await get_user(uid)
            await update.message.reply_text(
                f"✅ *রিকোয়েস্ট পাঠানো হয়েছে!*\n🔑 TrxID: {txn_id}\n💰 {amount} TK\n⏳ Admin confirm করবেন...",
                parse_mode="Markdown"
            )
            await update.message.reply_text(
                f"🏪 *Mail Shop* মেনু\n💰 ব্যালেন্স: *{db_user['balance']:.2f} TK*",
                reply_markup=main_menu_keyboard(), parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ সঠিক পরিমাণ দিন!")
        return

    if awaiting == "admin_stock_items" and user.id in ADMIN_IDS:
        stock_info = context.user_data.pop("admin_add_stock", None)
        context.user_data.pop("awaiting", None)
        if stock_info:
            items = [l.strip() for l in text.split("\n") if l.strip()]
            await add_stock(stock_info["product_key"], stock_info["variant_key"], items)
            await update.message.reply_text(f"✅ *{len(items)} টি আইটেম যোগ হয়েছে!*", parse_mode="Markdown")
        return

    if awaiting == "admin_approve_deposit" and user.id in ADMIN_IDS:
        context.user_data.pop("awaiting", None)
        try:
            parts = text.split()
            target_uid, amount = parts[0], float(parts[1])
            db_user = await get_user(target_uid)
            bonus = next((b["bonus"] for b in DEPOSIT_BONUSES if b["min"] <= amount <= b["max"]), 0)
            new_balance = db_user["balance"] + amount + bonus
            await update_user(target_uid, {"balance": new_balance, "deposited_today": db_user["deposited_today"] + amount})
            await clear_pending_deposit(target_uid)
            try:
                await context.bot.send_message(int(target_uid),
                    f"✅ *ডিপোজিট সফল!*\n💰 {amount} TK + 🎁 {bonus} TK বোনাস\n💳 ব্যালেন্স: {new_balance:.2f} TK",
                    parse_mode="Markdown")
            except: pass
            await update.message.reply_text(f"✅ Approved {amount} + {bonus} TK bonus for {target_uid}")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
        return

    if awaiting == "admin_broadcast" and user.id in ADMIN_IDS:
        context.user_data.pop("awaiting", None)
        users = await get_all_users()
        success = 0
        for target_uid in users:
            try:
                await context.bot.send_message(int(target_uid), text)
                success += 1
            except: pass
        await update.message.reply_text(f"📢 {success}/{len(users)} জনকে পাঠানো হয়েছে।")
        return

    if text.startswith("/approve") and user.id in ADMIN_IDS:
        parts = text.split()
        if len(parts) == 3:
            target_uid, amount = parts[1], float(parts[2])
            db_user = await get_user(target_uid)
            bonus = next((b["bonus"] for b in DEPOSIT_BONUSES if b["min"] <= amount <= b["max"]), 0)
            new_balance = db_user["balance"] + amount + bonus
            await update_user(target_uid, {"balance": new_balance, "deposited_today": db_user["deposited_today"] + amount})
            await clear_pending_deposit(target_uid)
            try:
                await context.bot.send_message(int(target_uid),
                    f"✅ *ডিপোজিট সফল!*\n💰 {amount} TK + 🎁 {bonus} TK\n💳 ব্যালেন্স: {new_balance:.2f} TK",
                    parse_mode="Markdown")
            except: pass
            await update.message.reply_text(f"✅ Approved {amount} TK for {target_uid}")
        return

    await update.message.reply_text("🏪 *Mail Shop* মেনু:", reply_markup=main_menu_keyboard(), parse_mode="Markdown")


async def _process_purchase(query, uid, product_key, variant_key, qty):
    variant = await get_variant(product_key, variant_key)
    total_cost = variant["price"] * qty
    db_user = await get_user(uid)
    if db_user["balance"] < total_cost:
        await query.edit_message_text(
            f"❌ *অপর্যাপ্ত ব্যালেন্স!*\n💰 আপনার: {db_user['balance']:.2f} TK\n💸 প্রয়োজন: {total_cost:.2f} TK",
            reply_markup=back_keyboard("shop"), parse_mode="Markdown"
        )
        return
    if len(variant["stock"]) < qty:
        await query.edit_message_text("❌ *স্টক শেষ!*", reply_markup=back_keyboard("shop"), parse_mode="Markdown")
        return
    items = await pop_stock(product_key, variant_key, qty)
    if not items:
        await query.edit_message_text("❌ *স্টক শেষ!*", reply_markup=back_keyboard("shop"), parse_mode="Markdown")
        return
    new_balance = db_user["balance"] - total_cost
    await update_user(uid, {"balance": new_balance, "spent_today": db_user["spent_today"] + total_cost, "total_spent": db_user["total_spent"] + total_cost})
    order_id = uuid.uuid4().hex[:16].upper()
    await add_order({"order_id": order_id, "user_id": uid, "product": product_key, "variant": variant_key, "qty": qty, "cost": total_cost, "date": datetime.datetime.now().isoformat()})
    items_text = "\n".join([f"`{item}`" for item in items])
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    await query.edit_message_text(
        f"✅ *অর্ডার সফল!*\n\n📅 {now}\n💰 {total_cost:.2f} TK\n🧾 `{order_id}`\n\n📦 *Accounts:*\n{items_text}\n\n💳 বাকি: {new_balance:.2f} TK",
        parse_mode="Markdown"
    )
    db_user_updated = await get_user(uid)
    await query.message.reply_text(
        f"🏪 *Mail Shop* মেনু\n💰 ব্যালেন্স: *{db_user_updated['balance']:.2f} TK*",
        reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )


async def _process_purchase_msg(update, context, uid, product_key, variant_key, qty):
    variant = await get_variant(product_key, variant_key)
    total_cost = variant["price"] * qty
    db_user = await get_user(uid)
    if db_user["balance"] < total_cost:
        await update.message.reply_text(
            f"❌ *অপর্যাপ্ত ব্যালেন্স!*\n💰 আপনার: {db_user['balance']:.2f} TK\n💸 প্রয়োজন: {total_cost:.2f} TK",
            reply_markup=back_keyboard("shop"), parse_mode="Markdown"
        )
        return
    if len(variant["stock"]) < qty:
        await update.message.reply_text("❌ *স্টক শেষ!*", reply_markup=back_keyboard("shop"), parse_mode="Markdown")
        return
    items = await pop_stock(product_key, variant_key, qty)
    if not items:
        await update.message.reply_text("❌ *স্টক শেষ!*", reply_markup=back_keyboard("shop"), parse_mode="Markdown")
        return
    new_balance = db_user["balance"] - total_cost
    await update_user(uid, {"balance": new_balance, "spent_today": db_user["spent_today"] + total_cost, "total_spent": db_user["total_spent"] + total_cost})
    order_id = uuid.uuid4().hex[:16].upper()
    await add_order({"order_id": order_id, "user_id": uid, "product": product_key, "variant": variant_key, "qty": qty, "cost": total_cost, "date": datetime.datetime.now().isoformat()})
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    await update.message.reply_text(
        f"✅ *অর্ডার সফল!*\n\n📅 {now}\n📦 {qty}টি\n💰 {total_cost:.2f} TK\n🧾 `{order_id}`\n💳 বাকি: {new_balance:.2f} TK",
        parse_mode="Markdown"
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Mail", "Password"])
    for item in items:
        p = item.split(":", 1) if ":" in item else [item, ""]
        writer.writerow(p)
    csv_bytes = io.BytesIO(output.getvalue().encode("utf-8"))
    csv_bytes.name = f"order_{order_id}.csv"
    await update.message.reply_document(document=csv_bytes, filename=f"order_{order_id}.csv",
        caption=f"📋 *{qty}টি Account*\nOrder: `{order_id}`", parse_mode="Markdown")
    db_user_updated = await get_user(uid)
    await update.message.reply_text(
        f"🏪 *Mail Shop* মেনু\n💰 ব্যালেন্স: *{db_user_updated['balance']:.2f} TK*",
        reply_markup=main_menu_keyboard(), parse_mode="Markdown"
    )
