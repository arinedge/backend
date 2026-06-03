import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_active_verified_user
from app.models.user import User
from app.schemas.broker import BrokerCreate, BrokerUpdate, BrokerOut, BrokerResponse
from app.services.broker_service import BrokerService

router = APIRouter(tags=["Brokers"])


@router.get("/", response_model=list[BrokerResponse])
def list_brokers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_verified_user),
):
    service = BrokerService(db)
    return service.get_user_brokers(current_user.id)


@router.post("/", response_model=BrokerResponse, status_code=status.HTTP_201_CREATED)
def create_broker(
    data: BrokerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_verified_user),
):
    service = BrokerService(db)
    return service.create_broker(current_user.id, data.model_dump())


@router.get("/{broker_id}", response_model=BrokerResponse)
def get_broker(
    broker_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_verified_user),
):
    service = BrokerService(db)
    broker = service.get_broker(broker_id, current_user.id)
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")
    return broker


@router.put("/{broker_id}", response_model=BrokerResponse)
def update_broker(
    broker_id: uuid.UUID,
    data: BrokerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_verified_user),
):
    service = BrokerService(db)
    broker = service.update_broker(
        broker_id, current_user.id, data.model_dump(exclude_none=True)
    )
    if not broker:
        raise HTTPException(status_code=404, detail="Broker not found")
    return broker


@router.delete("/{broker_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_broker(
    broker_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_verified_user),
):
    service = BrokerService(db)
    if not service.delete_broker(broker_id, current_user.id):
        raise HTTPException(status_code=404, detail="Broker not found")
