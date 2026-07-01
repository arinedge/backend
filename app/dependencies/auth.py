import traceback
import uuid

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.utils.security import decode_access_token
from app.utils.logger import get_logger, LogContext

security_scheme = HTTPBearer(auto_error=False)
logger = get_logger(__name__)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")

        if not user_id or token_type != "access":
            raise credentials_exception

        user_uuid = uuid.UUID(user_id)
    except (JWTError, ValueError):
        logger.warning("JWT decode failed for token")
        raise credentials_exception

    try:
        user = db.query(User).filter(User.id == user_uuid).first()
    except Exception:
        logger.error("DB error fetching user:\n%s", traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not validate credentials due to an internal error",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user:
        logger.warning("JWT valid but user not found: %s", user_uuid)
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    LogContext.set("user_id", str(user.id))
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if not credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        user_id: str = payload.get("sub")
        token_type: str = payload.get("type")
        if not user_id or token_type != "access":
            return None
        user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
        if user and user.is_active:
            return user
    except Exception:
        logger.debug("Optional auth failed for token")
    return None


async def get_current_active_verified_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified",
        )
    return current_user


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
