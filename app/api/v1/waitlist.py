from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.waitlist_entry import WaitlistEntry, generate_referral_code
from app.schemas.waitlist import (
    WaitlistCreate,
    WaitlistResponse,
    ReferralStatsResponse,
)

router = APIRouter()

REFERRAL_BONUS = 5  # queue positions to move up per referral


@router.post("", response_model=WaitlistResponse, status_code=status.HTTP_201_CREATED)
def join_waitlist(data: WaitlistCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(WaitlistEntry)
        .filter(WaitlistEntry.email == data.email)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email is already on the waitlist.",
        )

    # Generate unique referral code
    code = generate_referral_code()
    while db.query(WaitlistEntry).filter(WaitlistEntry.referral_code == code).first():
        code = generate_referral_code()

    # Increment referrer's referral count if referred_by provided
    referrer = None
    if data.referred_by:
        referrer = (
            db.query(WaitlistEntry)
            .filter(WaitlistEntry.referral_code == data.referred_by)
            .first()
        )
        if referrer:
            referrer.referral_signups_count = (
                referrer.referral_signups_count + 1
            )

    max_pos = (
        db.query(func.max(WaitlistEntry.queue_position)).scalar() or 0
    )

    entry = WaitlistEntry(
        name=data.name,
        email=data.email,
        trading_experience=data.trading_experience,
        primary_interest=data.primary_interest,
        referred_by=data.referred_by,
        referral_code=code,
        queue_position=max_pos + 1,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    return WaitlistResponse(
        message=f"You're position #{entry.queue_position} on the waitlist!",
        queue_position=entry.queue_position,
        referral_code=entry.referral_code,
    )


@router.get("/stats/{email}", response_model=ReferralStatsResponse)
def referral_stats(email: str, db: Session = Depends(get_db)):
    entry = (
        db.query(WaitlistEntry)
        .filter(WaitlistEntry.email == email)
        .first()
    )
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email not found on waitlist.",
        )

    # Calculate effective position after referral bonuses
    bonus_positions = entry.referral_signups_count * REFERRAL_BONUS
    effective_position = max(1, entry.queue_position - bonus_positions)

    return ReferralStatsResponse(
        referral_code=entry.referral_code,
        referral_signups_count=entry.referral_signups_count,
        queue_position=entry.queue_position,
        position_after_referrals=effective_position,
    )
