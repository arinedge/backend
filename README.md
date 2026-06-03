# Portal Backend

FastAPI authentication backend with JWT tokens, email verification via Zavu, and PostgreSQL.

## Prerequisites

- Python 3.12+
- PostgreSQL (or use the Docker Compose setup)
- Zavudev account (for emails)

## Quick Start (Local)

```bash
# 1. Clone / enter project
cd portal/backend

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — update DATABASE_URL, JWT_SECRET_KEY, ZAVUDEV_API_KEY

# 5. Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 6. Seed test user (one time)
python seed.py

# 7. Open API docs
open http://localhost:8000/docs
```

## Quick Start (Docker)

```bash
# 1. Configure
cp .env.example .env
# Edit .env with your credentials

# 2. Build and start (API + PostgreSQL)
docker compose up -d --build

# 3. Seed test user
docker compose exec api python seed.py

# 4. Verify
curl http://localhost:8000/health
```

## Environment Variables (`.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | postgresql://... |
| `JWT_SECRET_KEY` | JWT signing secret (min 32 chars) | change-me |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime (minutes) | 30 |
| `ZAVUDEV_API_KEY` | Zavudev API key for emails | — |
| `FRONTEND_URL` | Angular app URL (for email links) | http://localhost:4200 |
| `DEBUG` | Enable docs and debug logging | false |

## API Endpoints

### Public (no token)

| Method | Endpoint | Body |
|--------|----------|------|
| `POST` | `/api/v1/auth/signup` | `{username, full_name, email, password, confirm_password, mobile?}` |
| `POST` | `/api/v1/auth/login` | `{email, password}` |
| `POST` | `/api/v1/auth/verify-email` | `{token}` |
| `POST` | `/api/v1/auth/resend-verification?email=` | — |
| `POST` | `/api/v1/auth/forgot-password` | `{email}` |
| `POST` | `/api/v1/auth/reset-password` | `{token, new_password, confirm_password}` |
| `GET` | `/health` | — |

### Protected (Bearer token)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/users/me` | Get current user profile |
| `PUT` | `/api/v1/users/me` | Update username, full_name, mobile |
| `DELETE` | `/api/v1/users/me` | Deactivate account |

## Auth Flow

1. Client calls `POST /signup` — user created, verification email sent via Zavu
2. User clicks verification link → Angular frontend calls `POST /verify-email` with token
3. User logs in via `POST /login` → receives JWT `{access_token, token_type: "bearer"}`
4. Angular stores token, sends it as `Authorization: Bearer <token>` header
5. Backend validates token via `get_current_user` dependency

## Project Structure

```
backend/
├── app/
│   ├── main.py                 # FastAPI entry point, CORS, middleware
│   ├── config.py               # Settings from .env (pydantic-settings)
│   ├── database.py             # SQLAlchemy engine, session, Base
│   ├── models/
│   │   └── user.py             # User model
│   ├── schemas/
│   │   └── user.py             # Pydantic request/response schemas
│   ├── api/v1/
│   │   ├── auth.py             # Auth endpoints (public)
│   │   └── users.py            # User endpoints (protected)
│   ├── services/
│   │   ├── auth.py             # Auth business logic
│   │   └── email.py            # Zavu email service
│   ├── dependencies/
│   │   └── auth.py             # JWT dependency injection
│   └── utils/
│       ├── security.py         # bcrypt, JWT, public_id generation
│       └── logger.py           # Structured JSON logging
├── alembic/                    # Database migrations
├── logs/                       # Log files (gitignored)
├── seed.py                     # Seed test user
├── test_zavu.py                # Test Zavu connectivity
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Logging

Logs are written to `logs/app.log` (plain text) and `logs/app.json.log` (JSON, filterable).

Filter examples:
```bash
# All errors
grep '"level": "ERROR"' logs/app.json.log

# Emails only
grep '"module": "email"' logs/app.json.log

# By correlation ID
grep '"correlation_id": "abc123"' logs/app.json.log
```

## Database Migrations

```bash
# Generate migration after model changes
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Troubleshooting

**Emails not sending:**
```bash
python test_zavu.py        # Test Zavu connectivity
tail -f logs/app.json.log  # Check email logs for errors
```

**bcrypt / passlib error:**
```bash
pip uninstall passlib -y
pip install bcrypt>=4.0.0
```
