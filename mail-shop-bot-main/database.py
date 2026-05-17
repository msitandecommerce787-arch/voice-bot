import os
import requests
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = os.environ.get("MONGODB_URI", "mongodb+srv://msitandecommerce787_db_user:UgKtVQB6A3L4IBwh@cluster0.ybd2e3z.mongodb.net/mailshop?appName=Cluster0")
SHEET_URL = os.environ.get("GOOGLE_SHEET_URL", "https://script.google.com/macros/s/AKfycbykJuRQtdwSJlWVdpmBazXGIngf3HOf49bFG2oyKMeDhPz70Vxbh6aZ3GT_8S5IH-tQQA/exec")

_client = AsyncIOMotorClient(MONGO_URI)
_db = _client["mailshop"]
users_col = _db["users"]
orders_col = _db["orders"]
stock_col = _db["stock"]

PRODUCTS = {
    "edu_mail": {
        "name": "🎓 Edu Mail",
        "variants": {
            "edu_24h": {"name": "Edu 24 Hours Live", "price": 1.55},
            "edu_72h": {"name": "Edu 72 Hours Live", "price": 2.0},
            "studio_mail": {"name": "Studio Mail", "price": 3.0}
        }
    },
    "gmail": {
        "name": "📧 Fresh Gmail",
        "variants": {"fresh_gmail": {"name": "Fresh Gmail", "price": 2.0}}
    },
    "hotmail": {
        "name": "📨 Hotmail Trust",
        "variants": {"hotmail_trust": {"name": "Hotmail Trust", "price": 2.5}}
    },
    "outlook": {
        "name": "📩 Outlook Trust",
        "variants": {"outlook_trust": {"name": "Outlook Trust", "price": 2.5}}
    },
    "facebook": {
        "name": "📱 Facebook",
        "variants": {"fb_account": {"name": "Facebook Account", "price": 5.0}}
    },
    "other": {
        "name": "🛍️ Other Goods",
        "variants": {"other_item": {"name": "Other Digital Item", "price": 3.0}}
    }
}

# ── Users ──
async def get_user(user_id):
    uid = str(user_id)
    user = await users_col.find_one({"_id": uid})
    if not user:
        user = {"_id": uid, "balance": 0.0, "deposited_today": 0.0,
                "spent_today": 0.0, "total_spent": 0.0, "name": "", "username": ""}
        await users_col.insert_one(user)
    return user

async def update_user(user_id, data):
    await users_col.update_one({"_id": str(user_id)}, {"$set": data}, upsert=True)

async def get_all_users():
    return {u["_id"]: u async for u in users_col.find()}

# ── Products ──
async def get_products():
    products = {}
    for pk, p in PRODUCTS.items():
        products[pk] = {"name": p["name"], "variants": {}}
        for vk, v in p["variants"].items():
            count = await stock_col.count_documents({"product": p["name"], "variant": v["name"], "sold": False})
            products[pk]["variants"][vk] = {"name": v["name"], "price": v["price"], "stock": ["x"] * count}
    return products

async def get_variant(product_key, variant_key):
    p = PRODUCTS[product_key]
    v = p["variants"][variant_key]
    count = await stock_col.count_documents({"product": p["name"], "variant": v["name"], "sold": False})
    return {"name": v["name"], "price": v["price"], "stock": ["x"] * count}

# ── Stock ──
async def add_stock(product_key, variant_key, items):
    p = PRODUCTS[product_key]
    v = p["variants"][variant_key]
    docs = [{"product": p["name"], "variant": v["name"], "account": item, "sold": False} for item in items]
    if docs:
        await stock_col.insert_many(docs)

async def pop_stock(product_key, variant_key, qty=1):
    p = PRODUCTS[product_key]
    v = p["variants"][variant_key]
    items = []
    async for doc in stock_col.find({"product": p["name"], "variant": v["name"], "sold": False}).limit(qty):
        items.append(doc)
    if len(items) < qty:
        return None
    accounts = [doc["account"] for doc in items]
    ids = [doc["_id"] for doc in items]
    await stock_col.update_many({"_id": {"$in": ids}}, {"$set": {"sold": True}})
    # Sheets এ লাল mark করো
    for account in accounts:
        try:
            requests.post(SHEET_URL, json={"action": "sell", "account": account}, timeout=5)
        except:
            pass
    return accounts

# ── Deposits ──
async def add_pending_deposit(user_id, amount):
    await update_user(user_id, {"pending_deposit": amount})

async def get_pending_deposit(user_id):
    user = await get_user(user_id)
    return user.get("pending_deposit")

async def clear_pending_deposit(user_id):
    await users_col.update_one({"_id": str(user_id)}, {"$unset": {"pending_deposit": ""}})

# ── Orders ──
async def add_order(order):
    await orders_col.insert_one(order)

# ── Legacy ──
def load_db(): return {}
def save_db(data): pass
