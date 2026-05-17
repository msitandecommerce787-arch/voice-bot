from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Shop Now", callback_data="shop"),
         InlineKeyboardButton("💳 Deposit", callback_data="deposit")],
        [InlineKeyboardButton("👤 Profile", callback_data="profile"),
         InlineKeyboardButton("🎁 Refer", callback_data="refer")],
        [InlineKeyboardButton("📞 Support", callback_data="support")]
    ])

def products_keyboard(products: dict):
    buttons = []
    for key, product in products.items():
        buttons.append([InlineKeyboardButton(product["name"], callback_data=f"product_{key}")])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)

def variants_keyboard(product_key: str, variants: dict):
    buttons = []
    for vkey, variant in variants.items():
        stock_count = len(variant["stock"])
        label = f"{variant['name']} | {variant['price']} TK | Stock: {stock_count}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"variant_{product_key}_{vkey}")])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data="shop")])
    return InlineKeyboardMarkup(buttons)

def purchase_mode_keyboard(product_key, variant_key):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Single Buy", callback_data=f"buy_single_{product_key}_{variant_key}")],
        [InlineKeyboardButton("📦 Bulk Buy", callback_data=f"buy_bulk_{product_key}_{variant_key}")],
        [InlineKeyboardButton("◀️ Back", callback_data=f"product_{product_key}")]
    ])

def deposit_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Send Transaction ID", callback_data="send_txn")],
        [InlineKeyboardButton("◀️ Back", callback_data="main_menu")]
    ])

def back_keyboard(target="main_menu"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Back", callback_data=target)]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Add Stock", callback_data="admin_add_stock"),
         InlineKeyboardButton("✅ Approve Deposit", callback_data="admin_approve")],
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
         InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("◀️ Back", callback_data="main_menu")]
    ])

def admin_products_keyboard(products: dict, action: str):
    buttons = []
    for key, product in products.items():
        buttons.append([InlineKeyboardButton(product["name"], callback_data=f"{action}_{key}")])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def admin_variants_keyboard(product_key: str, variants: dict, action: str):
    buttons = []
    for vkey, variant in variants.items():
        buttons.append([InlineKeyboardButton(variant["name"], callback_data=f"{action}_{product_key}_{vkey}")])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data="admin_add_stock")])
    return InlineKeyboardMarkup(buttons)


def persistent_reply_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🛍️ Shop Now"), KeyboardButton("💳 Deposit")],
            [KeyboardButton("👤 Profile"), KeyboardButton("🎁 Refer")],
            [KeyboardButton("📞 Support"), KeyboardButton("🔄 Restart")],
        ],
        resize_keyboard=True,
        is_persistent=True
    )
