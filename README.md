# Telegram Message Service API

A multi-tenant REST API for sending Telegram messages via the Telethon client. Each user connects their own Telegram account and sends messages through it. Built with FastAPI and MongoDB.

## Features

- **Multi-tenant** — Each user has their own Telegram credentials and session. Multiple users can send messages from different Telegram accounts through a single API.
- **JWT Authentication** — OAuth2 password flow with access/refresh token rotation. Refresh tokens are stored as SHA-256 hashes (never plaintext).
- **Admin / User roles** — Only admins can create and manage users. Users can only send messages and view their own logs.
- **Swagger UI** — Interactive API docs at `/docs` with built-in OAuth2 Authorize dialog.
- **Message logs** — Every sent message is logged to MongoDB with status, timestamp, and sender/receiver info.
- **Docker ready** — Includes Dockerfile and docker-compose.yml.

## How It Works

```
1. Admin creates a user (with their Telegram api_id, api_hash, phone)
2. User logs in → gets JWT access token
3. User calls /telegram/init → receives a verification code on Telegram
4. User calls /telegram/verify with the code → session is created
5. User calls /send with a phone number and message → message is sent via Telegram
```

Steps 3-4 only need to be done once. The session is saved in the `sessions/` directory and survives restarts.

## Tech Stack

- **FastAPI** — web framework
- **Telethon** — Telegram client library (MTProto)
- **MongoDB** + **PyMongo** — database
- **PyJWT** — JSON Web Tokens
- **passlib[bcrypt]** — password hashing
- **Docker** — containerization

## Prerequisites

- Python 3.11+ (or Docker)
- MongoDB
- Each user needs Telegram API credentials from [my.telegram.org](https://my.telegram.org)

## Quick Start with Docker

```bash
git clone https://github.com/yourusername/telegram-message-service.git
cd telegram-message-service

cp env.example .env
nano .env
```

Set `MONGO_URI=mongodb://mongo:27017` in `.env`, then:

```bash
docker compose up -d
```

API docs: `http://localhost:8001/docs`

## Manual Installation

```bash
git clone https://github.com/yourusername/telegram-message-service.git
cd telegram-message-service

pip install -r requirements.txt --break-system-packages

cp env.example .env
nano .env

python main.py
```

Keep `MONGO_URI=mongodb://localhost:27017` if MongoDB is running locally.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MONGO_URI` | MongoDB connection string. Use `mongodb://mongo:27017` for Docker, `mongodb://localhost:27017` for local | `mongodb://localhost:27017` |
| `MONGO_DB` | Database name | `telegram_server` |
| `SESSIONS_DIR` | Directory for Telegram session files | `./sessions` |
| `JWT_SECRET` | Secret key for signing access tokens (change this!) | — |
| `JWT_REFRESH_SECRET` | Secret key for refresh tokens (change this!) | — |
| `JWT_ALGORITHM` | JWT signing algorithm | `HS256` |
| `JWT_ACCESS_EXPIRE_MINUTES` | Access token lifetime in minutes | `30` |
| `JWT_REFRESH_EXPIRE_DAYS` | Refresh token lifetime in days | `7` |
| `ADMIN_USERNAME` | Default admin username (created on first run) | `admin` |
| `ADMIN_PASSWORD` | Default admin password (change this!) | — |
| `HOST` | API bind address | `0.0.0.0` |
| `PORT` | API port | `8001` |

## API Endpoints

### Auth

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/auth/login` | — | Login, returns access + refresh token |
| POST | `/auth/refresh` | — | Refresh expired access token |
| POST | `/auth/logout` | — | Revoke a refresh token |
| POST | `/auth/logout-all` | Bearer | Revoke all sessions for current user |
| GET | `/auth/me` | Bearer | Get current user info |

### Users (Admin only)

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/users` | Admin | Create a new user |
| GET | `/users` | Admin | List all users |
| DELETE | `/users/{username}` | Admin | Delete a user |

### Telegram

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/telegram/init` | Bearer | Start Telegram session (sends code to phone) |
| POST | `/telegram/verify` | Bearer | Verify the code and complete session |
| GET | `/telegram/status` | Bearer | Check Telegram connection status |

### Messages

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/send` | Bearer | Send a Telegram message to a phone number |
| GET | `/logs` | Bearer | View message logs (admin sees all, users see own) |

## Usage

### 1. Login as admin

```bash
curl -X POST http://localhost:8001/auth/login \
  -d "username=admin&password=YourStrongPassword123!"
```

### 2. Create a user (requires admin token)

```bash
curl -X POST http://localhost:8001/users \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john",
    "password": "securepass123",
    "telegram_phone": "+15551234567",
    "telegram_api_id": 12345678,
    "telegram_api_hash": "abcdef1234567890abcdef1234567890"
  }'
```

### 3. Connect Telegram (one-time setup)

```bash
# Login as the user
curl -X POST http://localhost:8001/auth/login \
  -d "username=john&password=securepass123"

# Start session — a code will be sent to the phone via Telegram
curl -X POST http://localhost:8001/telegram/init \
  -H "Authorization: Bearer <user_token>"

# Enter the code
curl -X POST http://localhost:8001/telegram/verify \
  -H "Authorization: Bearer <user_token>" \
  -H "Content-Type: application/json" \
  -d '{"code": "12345"}'
```

### 4. Send a message

```bash
curl -X POST http://localhost:8001/send \
  -H "Authorization: Bearer <user_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+15559876543",
    "message": "Your verification code is: 482917"
  }'
```

### Frontend Example

```javascript
// Login
const { access_token } = await fetch("/auth/login", {
  method: "POST",
  headers: { "Content-Type": "application/x-www-form-urlencoded" },
  body: "username=john&password=securepass123"
}).then(r => r.json());

// Send message
await fetch("/send", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${access_token}`
  },
  body: JSON.stringify({
    phone: "+15559876543",
    message: "Your verification code is: 482917"
  })
});
```

## Project Structure

```
telegram-message-service/
├── main.py              # FastAPI app and routes
├── auth.py              # JWT tokens, password hashing, auth dependencies
├── telegram.py          # Telethon multi-user session manager
├── database.py          # MongoDB connection and init
├── config.py            # Environment variable loader
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── supervisor.conf      # For non-Docker deployments
├── env.example          # Example .env file
├── .gitignore
├── .dockerignore
└── sessions/            # Telegram session files (gitignored)
```

## MongoDB Collections

```
telegram_server
├── users    — user accounts with Telegram credentials
├── tokens   — refresh tokens (SHA-256 hashed, TTL indexed)
└── logs     — message delivery logs
```

## Security

- Passwords → **bcrypt** hashed
- Refresh tokens → **SHA-256** hashed in DB, never stored as plaintext
- Token rotation → old refresh token is deleted on every refresh
- TTL index → expired tokens are auto-deleted by MongoDB
- User creation → admin only
- Telegram credentials are stored per-user in MongoDB — secure your database

## Warning

This uses the **Telegram Client API**, not the Bot API. Sending too many messages to unknown numbers may get your Telegram account restricted or banned. Use responsibly.

## License

MIT