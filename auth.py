
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
import jwt
from passlib.context import CryptContext

from config import (
    JWT_SECRET,
    JWT_REFRESH_SECRET,
    JWT_ALGORITHM,
    JWT_ACCESS_EXPIRE_MINUTES,
    JWT_REFRESH_EXPIRE_DAYS,
)
from database import get_db

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")



def hash_password(password: str) -> str:
    return pwd.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd.verify(plain, hashed)



def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user_id: str, username: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_ACCESS_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None



def save_refresh_token(user_id: str, username: str, token: str):
    db = get_db()
    db.tokens.insert_one({
        "user_id": user_id,
        "username": username,
        "refresh_token_hash": hash_token(token),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=JWT_REFRESH_EXPIRE_DAYS),
        "created_at": datetime.now(timezone.utc),
    })


def validate_refresh_token(token: str) -> dict | None:
    db = get_db()
    token_hash = hash_token(token)
    doc = db.tokens.find_one({"refresh_token_hash": token_hash})
    if not doc:
        return None
    if doc["expires_at"] < datetime.now(timezone.utc):
        db.tokens.delete_one({"_id": doc["_id"]})
        return None
    return doc


def revoke_refresh_token(token: str):
    db = get_db()
    db.tokens.delete_one({"refresh_token_hash": hash_token(token)})


def revoke_all_user_tokens(username: str):
    db = get_db()
    db.tokens.delete_many({"username": username})



from fastapi.security import OAuth2PasswordBearer

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(token: str = Depends(_oauth2_scheme)) -> dict:
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş token")

    db = get_db()
    user = db.users.find_one({"username": payload["username"]})
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")

    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem için admin yetkisi gerekli")
    return user