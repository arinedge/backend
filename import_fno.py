"""Import complete.json data into F&O database tables."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal, engine, Base
from app.services.fno_service import FnoService
from app.utils.logger import setup_logging, get_logger

setup_logging()
logger = get_logger("import_fno")


def main():
    json_path = os.path.join(os.path.dirname(__file__), "support_files", "complete.json")
    if not os.path.exists(json_path):
        logger.error("File not found: %s", json_path)
        sys.exit(1)

    logger.info("Creating tables if not exist...")
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        result = FnoService.load_instruments_from_json(db, json_path)
        logger.info("Import result: %s", result)
        print(f"\nImport complete:")
        print(f"  Symbols:     {result['symbols']}")
        print(f"  Expiries:    {result['expiries']}")
        print(f"  Instruments: {result['instruments']}")
        print(f"  Skipped:     {result['skipped']}")
    except Exception as e:
        logger.error("Import failed: %s", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
