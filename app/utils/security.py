import hashlib
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt

from app.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def create_access_token(subject: str | uuid.UUID, role: str = "user") -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    jti = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    to_encode = {
        "sub": str(subject),
        "exp": expire,
        "iat": now,
        "type": "access",
        "jti": jti,
        "role": role,
    }
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def create_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_verification_token() -> str:
    return uuid.uuid4().hex


def get_token_expiry(hours: int = 24) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def get_refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


def generate_public_id() -> str:
    letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    digits = "".join(secrets.choice(string.digits) for _ in range(4))
    return letters + digits
