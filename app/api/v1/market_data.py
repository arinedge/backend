import json
import traceback

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user_optional
from app.models.user import User
from app.models.broker import Broker
from app.schemas.market_data import MarketDataResponse
from app.services.market_data_service import MarketDataService
from app.services.broker_service import BrokerService
from app.services.ws_manager import market_ws_manager
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Market Data"])


@router.websocket("/ws")
async def market_data_ws(ws: WebSocket):
    await market_ws_manager.connect(ws)
    try:
        db = next(get_db())
        try:
            broker = (
                db.query(Broker)
                .filter(Broker.is_active == True, Broker.access_token.isnot(None))
                .first()
            )
            if not broker:
                logger.warning("WS connect: no active broker found")
                return
            service = MarketDataService(db, broker)
            data = await service.get_latest_market_data()
            await ws.send_text(json.dumps(data, default=str))
        except Exception:
            logger.error("WS connect: failed to send initial data\n%s", traceback.format_exc())
            return
        finally:
            db.close()

        logger.info("WS connect: sent initial market data to client")
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.error("WS connect: unexpected error\n%s", traceback.format_exc())
    finally:
        await market_ws_manager.disconnect(ws)


@router.get("/data", response_model=MarketDataResponse)
async def get_market_data(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    broker = _resolve_broker(db, current_user)
    service = MarketDataService(db, broker)
    return await service.get_latest_market_data()


@router.get("/refresh")
async def refresh_market_data(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    broker = _resolve_broker(db, current_user)
    service = MarketDataService(db, broker)
    data = await service.fetch_and_store_market_data()
    return {
        "status": "success",
        "indices": data,
    }


def _resolve_broker(
    db: Session, current_user: User | None
) -> Broker | None:
    if current_user:
        broker_service = BrokerService(db)
        brokers = broker_service.get_user_brokers(current_user.id)
        broker = next(
            (b for b in brokers if b.is_active and b.access_token), None
        )
        if broker:
            return broker

    return (
        db.query(Broker)
        .filter(Broker.is_active == True, Broker.access_token.isnot(None))
        .first()
    )
