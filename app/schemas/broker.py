import uuid
from datetime import datetime
from pydantic import BaseModel


class BrokerBase(BaseModel):
    broker_name: str
    app_name: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    username: str
    password: str
    mobile: str | None = None


class BrokerCreate(BrokerBase):
    pass


class BrokerUpdate(BaseModel):
    broker_name: str | None = None
    app_name: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    username: str | None = None
    password: str | None = None
    mobile: str | None = None
    otp: str | None = None
    is_active: bool | None = None


class BrokerOut(BrokerBase):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    otp: str | None = None
    is_active: bool
    last_sync_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BrokerResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    broker_name: str
    app_name: str | None = None
    mobile: str | None = None
    is_active: bool
    last_sync_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BrokerTokenResponse(BaseModel):
    message: str
    access_token: str | None = None
