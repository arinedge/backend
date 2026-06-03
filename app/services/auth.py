import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.schemas.user import UserCreate
from app.utils.security import (
    hash_password,
    verify_password,
    create_verification_token,
    get_token_expiry,
    generate_public_id,
)
from app.utils.logger import get_logger
from app.services.email import send_verification_email, send_password_reset_email
from app.config import get_settings

settings = get_settings()
logger = get_logger(__name__)


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
    def authenticate_user(db: Session, email: str, password: str) -> User | None:
        try:
            user = db.execute(
                select(User).where(User.email == email)
            ).scalar_one_or_none()
        except Exception:
            logger.error("DB error during authentication:\n%s", traceback.format_exc())
            raise

        if not user:
            logger.warning("Login failed — email not found: %s", email)
            return None
        if not verify_password(password, user.hashed_password):
            logger.warning("Login failed — wrong password for user id=%s", user.id)
            return None

        try:
            user.is_logged_in = True
            user.last_login_at = datetime.now(timezone.utc)
            user.login_count = (user.login_count or 0) + 1
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB error updating login state:\n%s", traceback.format_exc())
            raise

        logger.info("User authenticated id=%s email=%s", user.id, user.email)
        return user

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
    def reset_password(db: Session, token: str, new_password: str) -> bool:
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

        logger.info("Password reset successful for user id=%s", user.id)
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
