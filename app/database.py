from datetime import datetime, timezone
from copy import deepcopy
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

client = None
db = None

DEFAULT_USER = {
    "format": "PNG",
    "jpeg_quality": 95,
    "prefix": "",
    "suffix": "",
    "scale_in_filename": True,
    "thumbnail": True,
}

DEFAULT_BOT = {
    "_id": "main",
    "privacy": {"encryption": True, "show_api_keys": False},
    "processing": {"timeout": 120, "max_upload_mb": 20},
    "output": {"jpeg_quality": 95, "thumbnail": True},
    "rotation": {"enabled": True},
}

def _copy(value):
    return deepcopy(value)

async def connect():
    global client, db
    if not settings.mongodb_uri:
        raise RuntimeError("MONGODB_URI is not configured.")
    client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=10000)
    await client.admin.command("ping")
    db = client[settings.mongodb_database]
    await db.users.create_index("telegram_id", unique=True)
    await db.apis.create_index([("enabled", 1), ("last_used", 1), ("created_at", 1)])
    await db.temp_files.create_index("expires_at", expireAfterSeconds=0)
    await get_bot_settings()

async def close():
    global client, db
    if client:
        client.close()
    client = None
    db = None

def get_db():
    if db is None:
        raise RuntimeError("MongoDB is not connected.")
    return db

async def ensure_user(uid: int):
    await get_db().users.update_one(
        {"telegram_id": uid},
        {"$setOnInsert": {
            "telegram_id": uid,
            "settings": _copy(DEFAULT_USER),
            "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )

async def get_user_settings(uid: int):
    await ensure_user(uid)
    doc = await get_db().users.find_one({"telegram_id": uid}, {"settings": 1})
    data = _copy(DEFAULT_USER)
    data.update(doc.get("settings", {}) if doc else {})
    return data

async def update_user_settings(uid: int, values: dict):
    await ensure_user(uid)
    await get_db().users.update_one(
        {"telegram_id": uid},
        {"$set": {f"settings.{k}": v for k, v in values.items()}},
    )

async def reset_user_settings(uid: int):
    await get_db().users.update_one(
        {"telegram_id": uid},
        {"$set": {"settings": _copy(DEFAULT_USER)}},
        upsert=True,
    )

async def get_bot_settings():
    doc = await get_db().bot_settings.find_one({"_id": "main"})
    if not doc:
        await get_db().bot_settings.update_one(
            {"_id": "main"}, {"$setOnInsert": _copy(DEFAULT_BOT)}, upsert=True
        )
        doc = await get_db().bot_settings.find_one({"_id": "main"})
    # Fill missing nested defaults after upgrades.
    merged = _copy(DEFAULT_BOT)
    for section in ("privacy", "processing", "output", "rotation"):
        merged[section].update(doc.get(section, {}))
    return merged

async def set_bot(path: str, value):
    await get_db().bot_settings.update_one({"_id": "main"}, {"$set": {path: value}}, upsert=True)

async def add_api(label: str, encrypted: str):
    await get_db().apis.insert_one({
        "label": label,
        "key": encrypted,
        "enabled": True,
        "created_at": datetime.now(timezone.utc),
        "last_used": None,
    })

async def list_apis():
    return await get_db().apis.find().sort([("created_at", 1)]).to_list(length=10000)

def _oid(oid: str):
    try:
        return ObjectId(oid)
    except Exception:
        return None

async def toggle_api(oid: str):
    obj = _oid(oid)
    if not obj:
        return False
    doc = await get_db().apis.find_one({"_id": obj})
    if not doc:
        return False
    await get_db().apis.update_one({"_id": obj}, {"$set": {"enabled": not bool(doc.get("enabled", False))}})
    return True

async def delete_api(oid: str):
    obj = _oid(oid)
    if not obj:
        return False
    result = await get_db().apis.delete_one({"_id": obj})
    return result.deleted_count == 1

async def next_api(excluded_ids=None, rotate=True):
    excluded_ids = excluded_ids or []
    query = {"enabled": True}
    if excluded_ids:
        query["_id"] = {"$nin": excluded_ids}
    return await get_db().apis.find_one(
        query,
        sort=[("last_used", 1), ("created_at", 1)] if rotate else [("created_at", 1)],
    )

async def mark_api_used(oid):
    obj = _oid(oid)
    if obj:
        await get_db().apis.update_one(
            {"_id": obj},
            {"$set": {"last_used": datetime.now(timezone.utc)}},
        )

