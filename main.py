from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from database import get_db, init_db
import telegram
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    save_refresh_token,
    validate_refresh_token,
    revoke_refresh_token,
    revoke_all_user_tokens,
    get_current_user,
    require_admin,
)
from config import HOST, PORT, JWT_ACCESS_EXPIRE_MINUTES


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield
    await telegram.disconnect_all()


app = FastAPI(title="Telegram Sender API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)



class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

class RefreshRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str
class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)
    telegram_phone: str = Field(..., examples=["+905551234567"])
    telegram_api_id: int = Field(..., description="https://my.telegram.org adresinden alınır")
    telegram_api_hash: str = Field(..., description="https://my.telegram.org adresinden alınır")
    description: Optional[str] = None
class TelegramVerifyRequest(BaseModel):
    code: str
    password: Optional[str] = Field(None, description="2FA şifresi (varsa)")
class SendRequest(BaseModel):
    phone: str = Field(..., examples=["+905551234567"])
    message: str = Field(..., min_length=1, max_length=4096)


@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = get_db().users.find_one({"username": form.username})
    if not user or not verify_password(form.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Geçersiz kullanıcı adı veya şifre")

    user_id = str(user["_id"])
    access = create_access_token(user_id, user["username"], user["role"])
    refresh = create_refresh_token()
    save_refresh_token(user_id, user["username"], refresh)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=JWT_ACCESS_EXPIRE_MINUTES * 60,
    )


@app.post("/auth/refresh", response_model=TokenResponse, tags=["Auth"])
def refresh(req: RefreshRequest):
    token_doc = validate_refresh_token(req.refresh_token)
    if not token_doc:
        raise HTTPException(status_code=401, detail="Geçersiz veya süresi dolmuş refresh token")

    user = get_db().users.find_one({"username": token_doc["username"]})
    if not user:
        raise HTTPException(status_code=401, detail="Kullanıcı bulunamadı")

    revoke_refresh_token(req.refresh_token)

    user_id = str(user["_id"])
    access = create_access_token(user_id, user["username"], user["role"])
    refresh_new = create_refresh_token()
    save_refresh_token(user_id, user["username"], refresh_new)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh_new,
        expires_in=JWT_ACCESS_EXPIRE_MINUTES * 60,
    )


@app.post("/auth/logout", tags=["Auth"])
def logout(req: LogoutRequest):
    revoke_refresh_token(req.refresh_token)
    return {"message": "Çıkış başarılı"}


@app.post("/auth/logout-all", tags=["Auth"], dependencies=[Depends(oauth2_scheme)])
def logout_all(user: dict = Depends(get_current_user)):
    revoke_all_user_tokens(user["username"])
    return {"message": "Tüm oturumlar kapatıldı"}


@app.get("/auth/me", tags=["Auth"], dependencies=[Depends(oauth2_scheme)])
def me(user: dict = Depends(get_current_user)):
    return {
        "username": user["username"],
        "role": user["role"],
        "telegram_phone": user["telegram_phone"],
        "telegram_connected": user["telegram_connected"],
        "description": user.get("description", ""),
        "created_at": user["created_at"],
    }


@app.post("/users", tags=["Users (Admin)"], dependencies=[Depends(oauth2_scheme)])
def create_user(req: CreateUserRequest, admin: dict = Depends(require_admin)):
    existing = get_db().users.find_one({"username": req.username})
    if existing:
        raise HTTPException(status_code=409, detail="Bu kullanıcı adı zaten mevcut")

    get_db().users.insert_one({
        "username": req.username,
        "password_hash": hash_password(req.password),
        "role": "user",
        "telegram_phone": req.telegram_phone,
        "telegram_api_id": req.telegram_api_id,
        "telegram_api_hash": req.telegram_api_hash,
        "description": req.description or "",
        "telegram_connected": False,
        "created_at": datetime.now(timezone.utc),
    })

    return {"message": "Kullanıcı oluşturuldu", "username": req.username}


@app.get("/users", tags=["Users (Admin)"], dependencies=[Depends(oauth2_scheme)])
def list_users(admin: dict = Depends(require_admin)):
    users = list(get_db().users.find({}, {"password_hash": 0, "_id": 0}).sort("created_at", -1))
    return {"users": users, "count": len(users)}


@app.delete("/users/{username}", tags=["Users (Admin)"], dependencies=[Depends(oauth2_scheme)])
def delete_user(username: str, admin: dict = Depends(require_admin)):
    if username == admin["username"]:
        raise HTTPException(status_code=400, detail="Kendini silemezsin")

    result = get_db().users.delete_one({"username": username})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı")

    revoke_all_user_tokens(username)
    return {"message": f"'{username}' silindi"}


@app.post("/telegram/init", tags=["Telegram"], dependencies=[Depends(oauth2_scheme)])
async def telegram_init(user: dict = Depends(get_current_user)):
    if not user.get("telegram_phone"):
        raise HTTPException(status_code=400, detail="Kullanıcıda telegram_phone tanımlı değil")
    if not user.get("telegram_api_id") or not user.get("telegram_api_hash"):
        raise HTTPException(status_code=400, detail="Kullanıcıda telegram_api_id/api_hash tanımlı değil")

    result = await telegram.start_session(
        user["username"], user["telegram_phone"],
        user["telegram_api_id"], user["telegram_api_hash"],
    )

    if result["status"] == "already_authorized":
        get_db().users.update_one(
            {"username": user["username"]},
            {"$set": {"telegram_connected": True}},
        )
        return {"message": "Telegram zaten bağlı", "phone": result["phone"]}

    return {"message": "Kod gönderildi. POST /telegram/verify ile doğrula."}


@app.post("/telegram/verify", tags=["Telegram"], dependencies=[Depends(oauth2_scheme)])
async def telegram_verify(req: TelegramVerifyRequest, user: dict = Depends(get_current_user)):
    result = await telegram.verify_session(
        user["username"], user["telegram_phone"], req.code, req.password
    )

    if result["status"] == "2fa_required":
        raise HTTPException(status_code=400, detail="2FA şifresi gerekli. 'password' alanını ekle.")
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["detail"])

    get_db().users.update_one(
        {"username": user["username"]},
        {"$set": {"telegram_connected": True}},
    )

    return {"message": "Telegram bağlandı", "name": result.get("name"), "phone": result.get("phone")}


@app.get("/telegram/status", tags=["Telegram"], dependencies=[Depends(oauth2_scheme)])
async def telegram_status(user: dict = Depends(get_current_user)):
    return await telegram.get_session_status(
        user["username"], user["telegram_api_id"], user["telegram_api_hash"],
    )


@app.post("/send", tags=["Messages"], dependencies=[Depends(oauth2_scheme)])
async def send_message(req: SendRequest, user: dict = Depends(get_current_user)):
    if not user.get("telegram_connected"):
        raise HTTPException(
            status_code=400,
            detail="Telegram bağlantısı yok. Önce /telegram/init ve /telegram/verify yap.",
        )

    result = await telegram.send_message(
        user["username"], user["telegram_api_id"], user["telegram_api_hash"],
        req.phone, req.message,
    )

    get_db().logs.insert_one({
        "username": user["username"],
        "from_phone": user["telegram_phone"],
        "to_phone": req.phone,
        "message": req.message,
        "success": result["success"],
        "detail": result["detail"],
        "created_at": datetime.now(timezone.utc),
    })

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["detail"])

    return {"success": True, "detail": "Mesaj gönderildi"}


@app.get("/logs", tags=["Logs"], dependencies=[Depends(oauth2_scheme)])
def get_logs(limit: int = 50, user: dict = Depends(get_current_user)):
    query = {} if user["role"] == "admin" else {"username": user["username"]}
    logs = list(get_db().logs.find(query, {"_id": 0}).sort("created_at", -1).limit(limit))
    return {"logs": logs, "count": len(logs)}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)