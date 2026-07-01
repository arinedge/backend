import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, status

from app.config import get_settings

settings = get_settings()

_rate_store: dict = defaultdict(list)
_rate_lock = Lock()


def check_rate_limit(
    request: Request,
    endpoint: str,
    key_suffix: str | None = None,
    max_attempts: int = 5,
    window_minutes: int = 15,
):
    """Simple in-memory rate limiter.

    WARNING: Single-process only. For multi-worker deployments, replace with
    Redis-based rate limiting.
    """
    if not settings.RATE_LIMIT_ENABLED:
        return

    client_ip = "unknown"
    if request:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        elif request.client:
            client_ip = request.client.host or "unknown"

    key = f"{endpoint}:{client_ip}"
    if key_suffix:
        key = f"{key}:{key_suffix}"

    now = time.time()
    window_seconds = window_minutes * 60

    with _rate_lock:
        records = _rate_store[key]
        cutoff = now - window_seconds
        records = [t for t in records if t > cutoff]
        _rate_store[key] = records

        if len(records) >= max_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please try again later.",
            )

        records.append(now)
