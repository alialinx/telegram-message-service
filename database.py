from pymongo import MongoClient, DESCENDING
from passlib.context import CryptContext
from datetime import datetime, timezone
from config import MONGO_URI, MONGO_DB, ADMIN_USERNAME, ADMIN_PASSWORD

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]


def get_db():
    return db


def init_db():
    db.users.create_index("username", unique=True)
    db.tokens.create_index("refresh_token_hash", unique=True)
    db.tokens.create_index("expires_at", expireAfterSeconds=0)
    db.logs.create_index([("username", 1), ("created_at", DESCENDING)])

    admin = db.users.find_one({"username": ADMIN_USERNAME})
    if not admin:
        db.users.insert_one({
            "username": ADMIN_USERNAME,
            "password_hash": pwd.hash(ADMIN_PASSWORD),
            "role": "admin",
            "telegram_phone": "",
            "description": "Sistem admin",
            "telegram_connected": False,
            "created_at": datetime.now(timezone.utc),
        })
