import json
from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_settings = get_settings()

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.Redis(
            host=_settings.REDIS_HOST,
            port=_settings.REDIS_PORT,
            password=_settings.REDIS_PASSWORD or None,
            db=_settings.REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        try:
            await _redis_pool.ping()
            logger.info("Connected to Redis at %s:%s", _settings.REDIS_HOST, _settings.REDIS_PORT)
        except Exception as e:
            logger.warning("Redis connection failed — caching disabled: %s", e)
            _redis_pool = None
    return _redis_pool


async def close_redis():
    global _redis_pool
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None
        logger.info("Redis connection closed")


async def cache_get(key: str) -> Any | None:
    r = await get_redis()
    if r is None:
        return None
    try:
        val = await r.get(key)
        if val is None:
            return None
        return json.loads(val)
    except Exception as e:
        logger.debug("Redis cache_get error for %s: %s", key, e)
        return None


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    r = await get_redis()
    if r is None:
        return
    try:
        expire = ttl if ttl is not None else _settings.REDIS_CACHE_TTL
        await r.setex(key, expire, json.dumps(value, default=str))
    except Exception as e:
        logger.debug("Redis cache_set error for %s: %s", key, e)


async def cache_delete(key: str) -> None:
    r = await get_redis()
    if r is None:
        return
    try:
        await r.delete(key)
    except Exception as e:
        logger.debug("Redis cache_delete error for %s: %s", key, e)


async def cache_delete_pattern(pattern: str) -> None:
    r = await get_redis()
    if r is None:
        return
    try:
        cursor = 0
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await r.delete(*keys)
            if cursor == 0:
                break
    except Exception as e:
        logger.debug("Redis cache_delete_pattern error for %s: %s", pattern, e)
