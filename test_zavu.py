"""Quick test: verify Zavu connectivity and send a test email."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.utils.logger import setup_logging, get_logger
from app.services.email import send_email

setup_logging()
logger = get_logger("zavu-test")

TEST_EMAIL = "arinedgehq@gmail.com"


def test_zavu():
    logger.info("Testing Zavu connectivity...")
    logger.info("Sending test email to %s", TEST_EMAIL)

    sent = send_email(
        to_email=TEST_EMAIL,
        subject="Zavu Test Email — Portal Backend",
        text_body="This is a test email from Portal Backend to verify Zavu integration.",
    )

    if sent:
        logger.info("SUCCESS: Test email sent via Zavu")
        print("Test email sent successfully")
    else:
        logger.error("FAILED: Could not send test email — check logs for details")
        print("Test email FAILED — check logs/app.log and logs/app.json.log for details")


if __name__ == "__main__":
    test_zavu()
