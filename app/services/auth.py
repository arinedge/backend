import hashlib
import traceback
import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_session import UserSession
from app.models.login_audit import LoginAuditEvent
from app.schemas.user import UserCreate
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    hash_token,
    create_verification_token,
    get_token_expiry,
    get_refresh_token_expiry,
    generate_public_id,
)
from app.utils.logger import get_logger
from app.services.email import send_verification_email, send_password_reset_email
from app.config import get_settings

settings = get_settings()
logger = get_logger(__name__)


def _hash_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def _get_client_ip(request: Request | None) -> str | None:
    if not request:
        return None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _log_audit(
    db: Session,
    event_type: str,
    success: bool,
    user_id: uuid.UUID | None = None,
    email: str | None = None,
    reason: str | None = None,
    request: Request | None = None,
):
    try:
        ip = _get_client_ip(request)
        ip_hash = _hash_ip(ip) if ip else None
        user_agent = request.headers.get("User-Agent") if request else None
        event = LoginAuditEvent(
            user_id=user_id,
            email=email,
            event_type=event_type,
            ip_hash=ip_hash,
            user_agent=user_agent,
            success=success,
            reason=reason,
        )
        db.add(event)
        db.commit()
    except Exception:
        db.rollback()
        logger.error("Failed to log audit event:\n%s", traceback.format_exc())


def _set_refresh_cookie(response, refresh_token: str):
    max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=max_age,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response):
    response.delete_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        path="/api/v1/auth",
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


class AuthService:

    @staticmethod
    def _generate_unique_public_id(db: Session) -> str:
        for _ in range(10):
            pid = generate_public_id()
            try:
                exists = db.execute(
                    select(User).where(User.public_id == pid)
                ).scalar_one_or_none()
            except Exception:
                logger.error("DB error checking public_id:\n%s", traceback.format_exc())
                raise
            if not exists:
                return pid
        raise RuntimeError("Failed to generate a unique public_id")

    @staticmethod
    def register_user(db: Session, data: UserCreate) -> User:
        logger.info("Registering user username=%s email=%s", data.username, data.email)

        try:
            existing = db.execute(
                select(User).where(
                    (User.email == data.email) | (User.username == data.username)
                )
            ).scalar_one_or_none()
        except Exception:
            logger.error("DB error checking existing user:\n%s", traceback.format_exc())
            raise

        if existing:
            if existing.email == data.email:
                raise ValueError("Email already registered")
            raise ValueError("Username already taken")

        try:
            user = User(
                public_id=AuthService._generate_unique_public_id(db),
                username=data.username,
                full_name=data.full_name,
                email=data.email,
                hashed_password=hash_password(data.password),
                mobile=data.mobile,
                email_verify_token=create_verification_token(),
                email_verify_token_expires=get_token_expiry(
                    settings.EMAIL_VERIFY_TOKEN_EXPIRE_HOURS
                ),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()
            logger.error("DB error creating user:\n%s", traceback.format_exc())
            raise

        logger.info(
            "User created id=%s public_id=%s username=%s",
            user.id, user.public_id, user.username,
        )
        return user

    @staticmethod
    def authenticate_user(
        db: Session, email: str, password: str, request: Request | None = None
    ) -> tuple[User, str, str] | None:
        """Returns (user, access_token, refresh_token) on success, None on failure."""
        try:
            user = db.execute(
                select(User).where(User.email == email)
            ).scalar_one_or_none()
        except Exception:
            logger.error("DB error during authentication:\n%s", traceback.format_exc())
            raise

        if not user:
            logger.warning("Login failed — email not found: %s", email)
            _log_audit(db, "login_failed", False, email=email, reason="email_not_found", request=request)
            return None
        if not verify_password(password, user.hashed_password):
            logger.warning("Login failed — wrong password for user id=%s", user.id)
            _log_audit(db, "login_failed", False, user.id, email, "wrong_password", request)
            return None

        refresh_token = create_refresh_token()
        refresh_token_hash = hash_token(refresh_token)

        try:
            session = UserSession(
                user_id=user.id,
                refresh_token_hash=refresh_token_hash,
                expires_at=get_refresh_token_expiry(),
            )
            if request:
                ip = _get_client_ip(request)
                session.ip_hash = _hash_ip(ip) if ip else None
                session.user_agent = request.headers.get("User-Agent")

            db.add(session)

            user.is_logged_in = True
            user.last_login_at = datetime.now(timezone.utc)
            user.login_count = (user.login_count or 0) + 1
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB error creating session:\n%s", traceback.format_exc())
            raise

        access_token = create_access_token(user.id, user.role)
        _log_audit(db, "login_success", True, user.id, email, request=request)

        logger.info("User authenticated id=%s email=%s", user.id, user.email)
        return user, access_token, refresh_token

    @staticmethod
    def refresh_session(
        db: Session, raw_refresh_token: str, request: Request | None = None
    ) -> tuple[User, str, str] | None:
        """Returns (user, new_access_token, new_refresh_token) or None."""
        if not raw_refresh_token:
            return None

        token_hash = hash_token(raw_refresh_token)

        try:
            session = db.execute(
                select(UserSession).where(
                    UserSession.refresh_token_hash == token_hash
                )
            ).scalar_one_or_none()
        except Exception:
            logger.error("DB error during refresh:\n%s", traceback.format_exc())
            return None

        if not session:
            logger.warning("Refresh failed — session not found")
            _log_audit(db, "refresh_failed", False, reason="session_not_found", request=request)
            return None

        if session.revoked_at:
            logger.warning("Refresh failed — session revoked")
            _log_audit(db, "refresh_failed", False, session.user_id, reason="session_revoked", request=request)
            return None

        if session.expires_at and session.expires_at < datetime.now(timezone.utc):
            logger.warning("Refresh failed — session expired")
            _log_audit(db, "refresh_failed", False, session.user_id, reason="session_expired", request=request)
            return None

        try:
            user = db.execute(
                select(User).where(User.id == session.user_id)
            ).scalar_one_or_none()
        except Exception:
            logger.error("DB error fetching user during refresh:\n%s", traceback.format_exc())
            return None

        if not user or not user.is_active:
            logger.warning("Refresh failed — user inactive or missing")
            _log_audit(db, "refresh_failed", False, session.user_id, reason="user_inactive", request=request)
            if session:
                session.revoked_at = datetime.now(timezone.utc)
                db.commit()
            return None

        new_refresh_token = create_refresh_token()
        new_token_hash = hash_token(new_refresh_token)

        try:
            session.refresh_token_hash = new_token_hash
            session.last_seen_at = datetime.now(timezone.utc)
            if request:
                ip = _get_client_ip(request)
                session.ip_hash = _hash_ip(ip) if ip else None
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB error rotating refresh token:\n%s", traceback.format_exc())
            return None

        access_token = create_access_token(user.id, user.role)
        _log_audit(db, "refresh_success", True, user.id, request=request)

        logger.info("Session refreshed for user id=%s", user.id)
        return user, access_token, new_refresh_token

    @staticmethod
    def logout_session(
        db: Session, raw_refresh_token: str, request: Request | None = None
    ) -> bool:
        """Revoke the session matching the given refresh token. Returns True if found."""
        if not raw_refresh_token:
            return False

        token_hash = hash_token(raw_refresh_token)

        try:
            session = db.execute(
                select(UserSession).where(
                    UserSession.refresh_token_hash == token_hash
                )
            ).scalar_one_or_none()
        except Exception:
            logger.error("DB error during logout:\n%s", traceback.format_exc())
            return False

        if not session:
            logger.warning("Logout — session not found for token")
            return False

        try:
            session.revoked_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB error revoking session:\n%s", traceback.format_exc())
            return False

        _log_audit(db, "logout", True, session.user_id, request=request)
        logger.info("Session revoked for user id=%s", session.user_id)
        return True

    @staticmethod
    def logout_all_sessions(
        db: Session, user_id: uuid.UUID, request: Request | None = None
    ) -> bool:
        try:
            sessions = db.execute(
                select(UserSession).where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                )
            ).scalars().all()

            now = datetime.now(timezone.utc)
            for s in sessions:
                s.revoked_at = now
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB error revoking all sessions:\n%s", traceback.format_exc())
            return False

        _log_audit(db, "logout_all", True, user_id, request=request)
        logger.info("All sessions revoked for user id=%s", user_id)
        return True

    @staticmethod
    def verify_email(db: Session, token: str) -> bool:
        try:
            user = db.execute(
                select(User).where(User.email_verify_token == token)
            ).scalar_one_or_none()
        except Exception:
            logger.error("DB error fetching user by verify token:\n%s", traceback.format_exc())
            raise

        if not user:
            logger.warning("Email verification failed — invalid token")
            return False

        if user.email_verify_token_expires and user.email_verify_token_expires < datetime.now(timezone.utc):
            logger.warning("Email verification failed — expired token for user id=%s", user.id)
            return False

        try:
            user.is_email_verified = True
            user.email_verify_token = None
            user.email_verify_token_expires = None
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB error updating email verification:\n%s", traceback.format_exc())
            raise

        logger.info("Email verified for user id=%s email=%s", user.id, user.email)
        return True

    @staticmethod
    def initiate_password_reset(db: Session, email: str) -> bool:
        try:
            user = db.execute(
                select(User).where(User.email == email)
            ).scalar_one_or_none()
        except Exception:
            logger.error("DB error fetching user for password reset:\n%s", traceback.format_exc())
            raise

        if not user:
            logger.info("Password reset requested for unknown email: %s", email)
            return True

        try:
            user.password_reset_token = create_verification_token()
            user.password_reset_token_expires = get_token_expiry(hours=1)
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB error saving password reset token:\n%s", traceback.format_exc())
            raise

        try:
            send_password_reset_email(
                user.email, user.full_name, user.password_reset_token
            )
        except Exception:
            logger.error("Failed to send password reset email:\n%s", traceback.format_exc())

        logger.info(
            "Password reset token generated for user id=%s email=%s",
            user.id, user.email,
        )
        return True

    @staticmethod
    def reset_password(db: Session, token: str, new_password: str, request: Request | None = None) -> bool:
        try:
            user = db.execute(
                select(User).where(User.password_reset_token == token)
            ).scalar_one_or_none()
        except Exception:
            logger.error("DB error fetching user by reset token:\n%s", traceback.format_exc())
            raise

        if not user:
            logger.warning("Password reset failed — invalid token")
            return False

        if (
            user.password_reset_token_expires
            and user.password_reset_token_expires < datetime.now(timezone.utc)
        ):
            logger.warning("Password reset failed — expired token for user id=%s", user.id)
            return False

        try:
            user.hashed_password = hash_password(new_password)
            user.password_reset_token = None
            user.password_reset_token_expires = None
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB error saving new password:\n%s", traceback.format_exc())
            raise

        AuthService.logout_all_sessions(db, user.id, request)
        _log_audit(db, "password_reset_success", True, user.id, request=request)

        logger.info("Password reset successful for user id=%s — sessions revoked", user.id)
        return True

    @staticmethod
    def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
        try:
            return db.execute(
                select(User).where(User.id == user_id)
            ).scalar_one_or_none()
        except Exception:
            logger.error("DB error fetching user by id:\n%s", traceback.format_exc())
            raise

    @staticmethod
    def update_user(
        db: Session,
        user: User,
        username: str | None,
        full_name: str | None,
        mobile: str | None,
    ) -> User:
        if username is not None:
            try:
                existing = db.execute(
                    select(User).where(
                        User.username == username, User.id != user.id
                    )
                ).scalar_one_or_none()
            except Exception:
                logger.error("DB error checking username availability:\n%s", traceback.format_exc())
                raise
            if existing:
                raise ValueError("Username already taken")
            user.username = username

        if full_name is not None:
            user.full_name = full_name

        if mobile is not None:
            user.mobile = mobile

        try:
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()
            logger.error("DB error updating user:\n%s", traceback.format_exc())
            raise

        logger.info("User updated id=%s", user.id)
        return user

    @staticmethod
    def logout_user(db: Session, user: User) -> None:
        try:
            user.is_logged_in = False
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB error during logout:\n%s", traceback.format_exc())
            raise

        logger.info("User logged out id=%s", user.id)
