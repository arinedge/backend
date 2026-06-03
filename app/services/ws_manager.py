import asyncio
import json
from typing import Any

from fastapi import WebSocket
import redis.asyncio as aioredis

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_settings = get_settings()

REDIS_PUBSUB_CHANNEL = "market_data:ws_broadcast"
_REDIS_CONN: aioredis.Redis | None = None


async def _get_redis_conn() -> aioredis.Redis | None:
    global _REDIS_CONN
    if _REDIS_CONN is None:
        try:
            _REDIS_CONN = aioredis.Redis(
                host=_settings.REDIS_HOST,
                port=_settings.REDIS_PORT,
                password=_settings.REDIS_PASSWORD or None,
                db=_settings.REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await _REDIS_CONN.ping()
        except Exception as e:
            logger.warning("Redis pub/sub unavailable: %s", e)
            _REDIS_CONN = None
    return _REDIS_CONN


class WSManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._pubsub_task: asyncio.Task | None = None
        self._own_conn: aioredis.Redis | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("WS client connected — total: %d", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("WS client disconnected — total: %d", len(self._connections))

    async def broadcast(self, data: dict[str, Any]) -> None:
        message = json.dumps(data, default=str)

        async with self._lock:
            dead: set[WebSocket] = set()
            for ws in self._connections:
                try:
                    await ws.send_text(message)
                except Exception:
                    dead.add(ws)
            self._connections -= dead
            if dead:
                logger.debug("Removed %d stale WS connections", len(dead))

        r = await _get_redis_conn()
        if r is not None:
            try:
                await r.publish(REDIS_PUBSUB_CHANNEL, message)
            except Exception:
                pass

    async def start_listener(self) -> None:
        r = await _get_redis_conn()
        if r is None:
            return
        try:
            pubsub = r.pubsub()
            await pubsub.subscribe(REDIS_PUBSUB_CHANNEL)
            logger.info("WS manager subscribed to Redis channel: %s", REDIS_PUBSUB_CHANNEL)
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                data_str: str | None = msg.get("data")
                if not data_str:
                    continue
                payload = await _parse_json(data_str)
                if payload is None:
                    continue
                async with self._lock:
                    dead = set()
                    for ws in self._connections:
                        try:
                            await ws.send_text(data_str)
                        except Exception:
                            dead.add(ws)
                    self._connections -= dead
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Redis pubsub listener stopped: %s", e)

    async def stop_listener(self) -> None:
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
            self._pubsub_task = None

    @property
    def count(self) -> int:
        return len(self._connections)


async def _parse_json(data: str) -> dict | None:
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


market_ws_manager = WSManager()
