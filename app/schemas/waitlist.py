import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class WaitlistCreate(BaseModel):
    name: str
    email: EmailStr
    trading_experience: str
    primary_interest: str
    referred_by: str | None = None


class WaitlistEntryOut(BaseModel):
    id: uuid.UUID
    queue_position: int | None
    referral_code: str
    referral_signups_count: int
    created_at: datetime
    model_config = {"from_attributes": True}


class WaitlistResponse(BaseModel):
    message: str
    queue_position: int | None = None
    referral_code: str | None = None


class ReferralStatsResponse(BaseModel):
    referral_code: str
    referral_signups_count: int
    queue_position: int
    position_after_referrals: int
