from zavudev import Zavudev

from app.config import get_settings
from app.utils.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)
zavu = Zavudev(api_key=settings.ZAVUDEV_API_KEY)


def send_email(to_email: str, subject: str, text_body: str) -> bool:
    logger.info(
        "Dispatching email via Zavu",
        extra={"extra_data": {"to": to_email, "subject": subject}},
    )

    try:
        response = zavu.messages.send(
            to=to_email,
            channel="email",
            subject=subject,
            text=text_body,
        )
        logger.info(
            "Email sent successfully",
            extra={"extra_data": {"to": to_email, "response": str(response)}},
        )
        return True
    except Exception:
        logger.exception(
            "Email send failed",
            extra={"extra_data": {"to": to_email, "subject": subject}},
        )
        return False


def send_verification_email(to_email: str, full_name: str, token: str) -> bool:
    verify_link = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    subject = "Verify your email address"
    text_body = (
        f"Welcome, {full_name}!\n\n"
        f"Please verify your email address by clicking the link below:\n"
        f"{verify_link}\n\n"
        f"This link will expire in {settings.EMAIL_VERIFY_TOKEN_EXPIRE_HOURS} hours.\n\n"
        f"Thanks,\nThe Portal Team"
    )
    return send_email(to_email, subject, text_body)


def send_password_reset_email(to_email: str, full_name: str, token: str) -> bool:
    reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    subject = "Reset your password"
    text_body = (
        f"Hi {full_name},\n\n"
        f"We received a request to reset your password. Use the link below to proceed:\n"
        f"{reset_link}\n\n"
        f"This link will expire in 1 hour. If you didn't request this, you can ignore this email.\n\n"
        f"Thanks,\nThe Portal Team"
    )
    return send_email(to_email, subject, text_body)
