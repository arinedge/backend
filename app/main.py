import asyncio
import json
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.v1 import api_router
from app.api.v1.sitemap import router as sitemap_router
from app.config import get_settings
from app.database import engine, Base, SessionLocal
from app.models.broker import Broker
from app.services.market_data_service import MarketDataService
from app.services.broker_service import BrokerService
from app.services.upstox_ws import UpstoxWSClient
from app.services.ws_manager import market_ws_manager
from app.utils.logger import setup_logging, get_logger, LogContext
from app.components.graph.pipeline import GraphPipeline
from app.utils.redis_cache import close_redis, cache_get

settings = get_settings()
setup_logging()
logger = get_logger(__name__)

_graph_pipeline: GraphPipeline | None = None
_graph_pipeline_task: asyncio.Task | None = None
_market_data_task: asyncio.Task | None = None
_upstox_ws: UpstoxWSClient | None = None
_upstox_ws_db: Session | None = None
_ws_tick_lock = asyncio.Lock()


async def _get_active_broker():
    db = SessionLocal()
    try:
        return (
            db.query(Broker)
            .filter(Broker.is_active == True, Broker.access_token.isnot(None))
            .first()
        )
    finally:
        db.close()


async def _initial_data_load():
    """Pre-populate Redis cache from DB on startup."""
    db = SessionLocal()
    try:
        broker = (
            db.query(Broker)
            .filter(Broker.is_active == True, Broker.access_token.isnot(None))
            .first()
        )
        if not broker:
            logger.info("No active broker — skipping initial data load")
            return
        service = MarketDataService(db, broker)
        await service.check_market_status()
        indices = await service.rebuild_indices_cache()
        if indices:
            logger.info("Initial data loaded into Redis: %d indices", len(indices))
        else:
            logger.info("No historical data in DB — will fetch on first request")
    except Exception:
        logger.error("Initial data load failed:\n%s", traceback.format_exc())
    finally:
        db.close()


async def _start_upstox_ws():
    global _upstox_ws, _upstox_ws_db
    broker = await _get_active_broker()
    if not broker or not broker.access_token:
        logger.warning("Cannot start Upstox WS: no active broker")
        return

    async def handle_ws_tick(tick: dict):
        async with _ws_tick_lock:
            global _upstox_ws_db
            if _upstox_ws_db is None:
                _upstox_ws_db = SessionLocal()
            db = _upstox_ws_db
            try:
                service = MarketDataService(db, broker)
                inst_key = tick.get("instrument_key", "")
                if inst_key.startswith(("NSE_FO", "BSE_FO")):
                    result = await service.process_option_tick(tick)
                else:
                    result = await service.process_ws_tick(tick)
                if result:
                    db.commit()
                    if not inst_key.startswith(("NSE_FO", "BSE_FO")):
                        indices = await service.rebuild_indices_cache()
                        payload = await cache_get("market_data:status")
                        if indices:
                            await market_ws_manager.broadcast({
                                "status": "success",
                                "market_status": payload or {},
                                "indices": indices,
                                "last_updated": result["fetched_at"],
                            })
            except Exception:
                logger.error("WS tick handler error:\n%s", traceback.format_exc())
                try:
                    db.rollback()
                except Exception:
                    pass

    client = UpstoxWSClient(broker.access_token, handle_ws_tick)
    _upstox_ws = client
    app.state.upstox_ws = client
    try:
        await client.start()
    except Exception as e:
        logger.error("Upstox WS failed: %s", e)
    finally:
        _upstox_ws = None
        if _upstox_ws_db is not None:
            _upstox_ws_db.close()
            _upstox_ws_db = None


async def _stop_upstox_ws():
    global _upstox_ws, _upstox_ws_db
    if _upstox_ws:
        await _upstox_ws.stop()
        _upstox_ws = None
        if _upstox_ws_db is not None:
            _upstox_ws_db.close()
            _upstox_ws_db = None


async def _market_data_poller():
    """Background task: checks market status and manages Upstox WS lifecycle."""
    logger.info("Market data poller started")
    first_run = True
    while True:
        if not first_run:
            await asyncio.sleep(60)
        first_run = False
        try:
            db = SessionLocal()
            try:
                broker = (
                    db.query(Broker)
                    .filter(Broker.is_active == True, Broker.access_token.isnot(None))
                    .first()
                )
                should_be_open = False
                if broker:
                    service = MarketDataService(db, broker)
                    await service.check_market_status()
                    should_be_open = await service._should_fetch_live()
                else:
                    logger.warning("No active broker with access_token found")

                global _upstox_ws
                if should_be_open and _upstox_ws is None:
                    logger.info("Market open — starting Upstox WebSocket")
                    asyncio.ensure_future(_start_upstox_ws())
                elif not should_be_open and _upstox_ws is not None:
                    logger.info("Market closed — stopping Upstox WebSocket")
                    await _stop_upstox_ws()

            except Exception:
                logger.error("Market data poller error:\n%s", traceback.format_exc())
            finally:
                db.close()
        except Exception:
            logger.error("Market data poller session error:\n%s", traceback.format_exc())


def _seed_default_broker():
    """Seed the default Upstox broker with the provided access token on first run."""
    try:
        db = SessionLocal()
        try:
            existing = db.query(Broker).filter(Broker.broker_name == "upstox").first()
            if not existing:
                broker = Broker(
                    broker_name="upstox",
                    app_name="ArinEdge",
                    username="system",
                    password="system",
                    access_token=settings.UPSTOX_ACCESS_TOKEN or "",
                    is_active=True,
                )
                db.add(broker)
                db.commit()
                logger.info("Default Upstox broker seeded")
        finally:
            db.close()
    except Exception as e:
        logger.warning("Could not seed default broker: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s ...", settings.APP_NAME, settings.APP_VERSION)
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables ensured")
    except Exception:
        logger.error("Failed to create database tables:\n%s", traceback.format_exc())
        raise

    _seed_default_broker()

    await _initial_data_load()

    global _market_data_task
    _market_data_task = asyncio.create_task(_market_data_poller())

    ws_listener = asyncio.create_task(market_ws_manager.start_listener())

    # Start graph intelligence pipeline
    if settings.GRAPH_PIPELINE_ENABLED:
        global _graph_pipeline, _graph_pipeline_task
        try:
            _graph_pipeline = GraphPipeline()
            _graph_pipeline_task = asyncio.create_task(
                _graph_pipeline.run_pipeline_loop(
                    interval_seconds=120,
                    initial_delay_seconds=settings.GRAPH_PIPELINE_INITIAL_DELAY_SECONDS,
                )
            )
            logger.info(
                "Graph intelligence pipeline started (interval=120s, initial_delay=%ss)",
                settings.GRAPH_PIPELINE_INITIAL_DELAY_SECONDS,
            )
        except Exception:
            logger.error("Failed to start graph pipeline:\n%s", traceback.format_exc())
    else:
        logger.info("Graph intelligence pipeline is DISABLED")

    yield

    await _stop_upstox_ws()

    if _market_data_task:
        _market_data_task.cancel()
        try:
            await _market_data_task
        except asyncio.CancelledError:
            pass

    await market_ws_manager.stop_listener()

    # Stop graph intelligence pipeline
    if _graph_pipeline_task:
        _graph_pipeline_task.cancel()
        try:
            await _graph_pipeline_task
        except asyncio.CancelledError:
            pass
        _graph_pipeline_task = None
        _graph_pipeline = None
        logger.info("Graph intelligence pipeline stopped")

    await close_redis()
    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://localhost:3000",
        "https://arinedge.com",
        "https://web.arinedge.com",
        settings.FRONTEND_URL,
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    correlation_id = LogContext.get("correlation_id", uuid.uuid4().hex[:12])
    logger.error(
        "Unhandled exception at %s %s | correlation_id=%s\n%s",
        request.method,
        request.url.path,
        correlation_id,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "correlation_id": correlation_id,
        },
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", uuid.uuid4().hex[:12])
    LogContext.set("correlation_id", correlation_id)

    logger.info(
        "%s %s",
        request.method,
        request.url.path,
        extra={"extra_data": {"client": request.client.host if request.client else "unknown"}},
    )

    try:
        response = await call_next(request)
        logger.debug(
            "Response %s %s → %s",
            request.method, request.url.path, response.status_code,
        )
        return response
    except Exception:
        logger.error(
            "Unhandled exception in middleware at %s %s\n%s",
            request.method,
            request.url.path,
            traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "correlation_id": correlation_id},
        )
    finally:
        LogContext.clear()


app.include_router(api_router)
app.include_router(sitemap_router)


@app.get("/health")
def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}
