import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.broker import Broker
from app.utils.logger import get_logger

logger = get_logger(__name__)


class BrokerService:
    def __init__(self, db: Session):
        self.db = db

    def create_broker(
        self, user_id: uuid.UUID, data: dict[str, Any]
    ) -> Broker:
        broker = Broker(user_id=user_id, **data)
        self.db.add(broker)
        self.db.commit()
        self.db.refresh(broker)
        logger.info("Broker created: %s for user %s", broker.broker_name, user_id)
        return broker

    def get_user_brokers(self, user_id: uuid.UUID) -> list[Broker]:
        return (
            self.db.query(Broker)
            .filter(Broker.user_id == user_id)
            .order_by(Broker.created_at.desc())
            .all()
        )

    def get_broker(
        self, broker_id: uuid.UUID, user_id: uuid.UUID
    ) -> Broker | None:
        return self.db.query(Broker).filter(
            Broker.id == broker_id, Broker.user_id == user_id
        ).first()

    def update_broker(
        self,
        broker_id: uuid.UUID,
        user_id: uuid.UUID,
        data: dict[str, Any],
    ) -> Broker | None:
        broker = self.get_broker(broker_id, user_id)
        if not broker:
            return None
        for key, value in data.items():
            if value is not None:
                setattr(broker, key, value)
        broker.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(broker)
        return broker

    def delete_broker(
        self, broker_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        broker = self.get_broker(broker_id, user_id)
        if not broker:
            return False
        self.db.delete(broker)
        self.db.commit()
        return True

    def get_active_broker_by_name(
        self, broker_name: str
    ) -> Broker | None:
        return self.db.query(Broker).filter(
            Broker.broker_name == broker_name, Broker.is_active == True
        ).first()

    def get_default_broker(self) -> Broker | None:
        return (
            self.db.query(Broker)
            .filter(Broker.is_active == True, Broker.access_token.isnot(None))
            .first()
        )
