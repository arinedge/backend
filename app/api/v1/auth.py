import traceback

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.user import (
    UserCreate,
    UserLogin,
    TokenResponse,
    LoginResponse,
    MessageResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    EmailVerifyRequest,
    UserResponse,
)
from app.services.auth import AuthService
from app.dependencies.auth import get_current_user, get_current_active_verified_user
from app.models.user import User
from app.utils.security import create_access_token
from app.utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.post(
    "/signup",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(
    data: UserCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        user = AuthService.register_user(db, data)
    except ValueError as e:
        logger.warning("Signup rejected — %s", e)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception:
        logger.error("Signup failed unexpectedly:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Registration failed due to an internal error")

    background_tasks.add_task(
        _send_verification_email_wrapper,
        user.email,
        user.full_name,
        user.email_verify_token,
    )

    logger.info("Signup complete for user id=%s — queued verification email", user.id)
    return MessageResponse(
        message="Registration successful. Please check your email to verify your account."
    )


def _send_verification_email_wrapper(email: str, full_name: str, token: str):
    try:
        from app.services.email import send_verification_email
        send_verification_email(email, full_name, token)
    except Exception:
        logger.error("Background verification email failed for %s:\n%s", email, traceback.format_exc())


@router.post("/login", response_model=LoginResponse)
def login(data: UserLogin, db: Session = Depends(get_db)):
    try:
        user = AuthService.authenticate_user(db, data.email, data.password)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        access_token = create_access_token(user.id)
        logger.info("Login successful for user id=%s (verified=%s)", user.id, user.is_email_verified)
        return LoginResponse(access_token=access_token, user=user, email_verified=user.is_email_verified)
    except HTTPException:
        raise
    except Exception:
        logger.error("Login failed unexpectedly for %s:\n%s", data.email, traceback.format_exc())
        raise HTTPException(status_code=500, detail="Login failed due to an internal error")


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(
    current_user: User = Depends(get_current_active_verified_user),
):
    return UserResponse(user=current_user)


@router.post("/logout", response_model=MessageResponse)
def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        AuthService.logout_user(db, current_user)
        return MessageResponse(message="Logged out successfully.")
    except Exception:
        logger.error("Logout failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Logout failed due to an internal error")


@router.post("/verify-email", response_model=MessageResponse)
def verify_email(data: EmailVerifyRequest, db: Session = Depends(get_db)):
    try:
        success = AuthService.verify_email(db, data.token)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired verification token",
            )
        return MessageResponse(message="Email verified successfully. You can now log in.")
    except HTTPException:
        raise
    except Exception:
        logger.error("Email verification failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Verification failed due to an internal error")


@router.post("/resend-verification", response_model=MessageResponse)
def resend_verification(
    data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    try:
        from sqlalchemy import select
        from app.models.user import User as UserModel
        from app.utils.security import create_verification_token, get_token_expiry
        from app.config import get_settings

        _settings = get_settings()
        user = db.execute(select(UserModel).where(UserModel.email == data.email)).scalar_one_or_none()

        if not user:
            return MessageResponse(
                message="If the email is registered, a new verification link has been sent."
            )

        if user.is_email_verified:
            return MessageResponse(message="Email is already verified.")

        user.email_verify_token = create_verification_token()
        user.email_verify_token_expires = get_token_expiry(
            _settings.EMAIL_VERIFY_TOKEN_EXPIRE_HOURS
        )
        db.commit()

        background_tasks.add_task(
            send_verification_email, user.email, user.full_name, user.email_verify_token
        )

        return MessageResponse(
            message="If the email is registered, a new verification link has been sent."
        )
    except Exception:
        logger.error("Resend verification failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to resend verification email")


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    data: ForgotPasswordRequest, db: Session = Depends(get_db)
):
    try:
        AuthService.initiate_password_reset(db, data.email)
        return MessageResponse(
            message="If the email is registered, a password reset link has been sent."
        )
    except Exception:
        logger.error("Forgot password failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Failed to process password reset request")


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        success = AuthService.reset_password(db, data.token, data.new_password)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired reset token",
            )
        return MessageResponse(message="Password reset successfully. You can now log in.")
    except HTTPException:
        raise
    except Exception:
        logger.error("Password reset failed:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Password reset failed due to an internal error")
