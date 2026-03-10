"""
Multi-user Telegram session yöneticisi.
Her kullanıcı kendi api_id, api_hash ve telefon numarası ile çalışır.
Session dosyaları sessions/ klasöründe tutulur.
"""
import os
from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    UserNotMutualContactError,
    PeerIdInvalidError,
    SessionPasswordNeededError,
)
from config import SESSIONS_DIR

_clients: dict[str, TelegramClient] = {}


def _session_path(username: str) -> str:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    return os.path.join(SESSIONS_DIR, username)


def _create_client(username: str, api_id: int, api_hash: str) -> TelegramClient:
    path = _session_path(username)
    return TelegramClient(path, api_id, api_hash)


async def start_session(username: str, phone: str, api_id: int, api_hash: str) -> dict:
    client = _create_client(username, api_id, api_hash)
    await client.connect()

    if await client.is_user_authorized():
        _clients[username] = client
        me = await client.get_me()
        return {"status": "already_authorized", "phone": me.phone}

    await client.send_code_request(phone)
    _clients[username] = client
    return {"status": "code_sent"}


async def verify_session(username: str, phone: str, code: str, password: str = None) -> dict:
    client = _clients.get(username)
    if not client:
        return {"status": "error", "detail": "Önce /telegram/init çağır"}

    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        if not password:
            return {"status": "2fa_required", "detail": "2FA şifresi gerekli"}
        await client.sign_in(password=password)

    me = await client.get_me()
    return {"status": "authorized", "phone": me.phone, "name": me.first_name}


async def send_message(username: str, api_id: int, api_hash: str, target_phone: str, message: str) -> dict:
    client = _clients.get(username)

    if not client:
        path = _session_path(username)
        if not os.path.exists(path + ".session"):
            return {"success": False, "detail": "Telegram oturumu bulunamadı. Önce bağlantı kur."}

        client = _create_client(username, api_id, api_hash)
        await client.connect()

        if not await client.is_user_authorized():
            return {"success": False, "detail": "Telegram oturumu geçersiz. Yeniden bağlan."}

        _clients[username] = client

    try:
        entity = await client.get_input_entity(target_phone)
        await client.send_message(entity, message)
        return {"success": True, "detail": "Mesaj gönderildi"}
    except FloodWaitError as e:
        return {"success": False, "detail": f"Telegram rate limit: {e.seconds}sn bekle"}
    except (UserNotMutualContactError, PeerIdInvalidError, ValueError):
        return {"success": False, "detail": "Numara Telegram'da bulunamadı veya erişilemiyor"}
    except Exception as e:
        return {"success": False, "detail": str(e)}


async def get_session_status(username: str, api_id: int, api_hash: str) -> dict:
    client = _clients.get(username)

    if not client:
        path = _session_path(username)
        if not os.path.exists(path + ".session"):
            return {"connected": False, "detail": "Session yok"}

        client = _create_client(username, api_id, api_hash)
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            return {"connected": False, "detail": "Session geçersiz"}

        _clients[username] = client

    me = await client.get_me()
    return {"connected": True, "phone": me.phone, "name": me.first_name}


async def disconnect_all():
    for _, client in _clients.items():
        if client.is_connected():
            await client.disconnect()
    _clients.clear()