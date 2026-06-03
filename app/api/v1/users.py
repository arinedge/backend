import traceback

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_active_verified_user
from app.models.user import User
from app.schemas.user import UserOut, UserUpdate, MessageResponse
from app.services.auth import AuthService
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_active_verified_user)):
    return current_user


@router.put("/me", response_model=UserOut)
def update_me(
    data: UserUpdate,
    current_user: User = Depends(get_current_active_verified_user),
    db: Session = Depends(get_db),
):
    try:
        user = AuthService.update_user(
            db, current_user, data.username, data.full_name, data.mobile
        )
    except ValueError as e:
        logger.warning("Profile update rejected for user id=%s: %s", current_user.id, e)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception:
        logger.error("Profile update failed for user id=%s:\n%s", current_user.id, traceback.format_exc())
        raise HTTPException(status_code=500, detail="Profile update failed due to an internal error")
    return user


@router.delete("/me", response_model=MessageResponse)
def delete_me(
    current_user: User = Depends(get_current_active_verified_user),
    db: Session = Depends(get_db),
):
    try:
        current_user.is_active = False
        db.commit()
        logger.info("Account deactivated for user id=%s", current_user.id)
        return MessageResponse(message="Account deactivated successfully.")
    except Exception:
        logger.error("Account deactivation failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Account deactivation failed due to an internal error")
