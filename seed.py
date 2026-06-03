"""Seed script: creates a test user via the AuthService."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, engine, Base
from app.services.auth import AuthService
from app.services.email import send_verification_email
from app.schemas.user import UserCreate
from app.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger("seed")


def seed():
    logger.info("Starting seed script")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        data = UserCreate(
            username="kiranbudati",
            full_name="Kiran Budati",
            email="arinedgehq@gmail.com",
            password="Admin@123",
            confirm_password="Admin@123",
            mobile="80080340884",
        )
        try:
            user = AuthService.register_user(db, data)
            logger.info(
                "User created successfully",
                extra={
                    "extra_data": {
                        "id": str(user.id),
                        "public_id": user.public_id,
                        "username": user.username,
                        "email": user.email,
                    }
                },
            )
            print(f"User created: {user.username} | public_id: {user.public_id} | id: {user.id}")
            print(f"Verification token: {user.email_verify_token}")
            print("Sending verification email...")

            sent = send_verification_email(user.email, user.full_name, user.email_verify_token)
            print(f"Verification email sent: {sent}")
        except ValueError as e:
            logger.error("Seed failed: %s", e)
            print(f"Error: {e}")
    finally:
        db.close()

    logger.info("Seed script finished")


if __name__ == "__main__":
    seed()
