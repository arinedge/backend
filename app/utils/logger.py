import contextvars
import json
import logging
import logging.handlers
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings

settings = get_settings()

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
LOG_JSON_FILE = os.path.join(LOG_DIR, "app.json.log")
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 30


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }

        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id

        if hasattr(record, "user_id"):
            log_entry["user_id"] = record.user_id

        if hasattr(record, "extra_data"):
            log_entry["extra_data"] = record.extra_data

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(log_entry, default=str)


class ConsoleFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[35m",  # magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        record.name = f"\033[1m{record.name}\033[0m"

        msg = super().format(record)

        extra_parts = []
        if hasattr(record, "correlation_id"):
            extra_parts.append(f"cid={record.correlation_id}")
        if hasattr(record, "user_id"):
            extra_parts.append(f"uid={record.user_id}")
        if extra_parts:
            msg += f"  [{', '.join(extra_parts)}]"

        return msg


class ContextFilter(logging.Filter):
    def __init__(self, allowed_modules: list[str] | None = None):
        super().__init__()
        self.allowed_modules = allowed_modules

    def filter(self, record: logging.LogRecord) -> bool:
        if self.allowed_modules and record.module not in self.allowed_modules:
            return False
        return True


class LogContext:
    _context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("log_context", default={})

    @classmethod
    def set(cls, key: str, value: Any):
        ctx = cls._context.get().copy()
        ctx[key] = value
        cls._context.set(ctx)

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        return cls._context.get().get(key, default)

    @classmethod
    def clear(cls):
        cls._context.set({})

    @classmethod
    def correlation_id(cls) -> str | None:
        return cls._context.get().get("correlation_id")

    @classmethod
    def user_id(cls) -> str | None:
        return cls._context.get().get("user_id")


class ContextAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        if LogContext.correlation_id():
            extra["correlation_id"] = LogContext.correlation_id()
        if LogContext.user_id():
            extra["user_id"] = LogContext.user_id()
        kwargs["extra"] = extra
        return msg, kwargs


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler (colored, human-readable)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    console_formatter = ConsoleFormatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Rotating file handler (plain text)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(funcName)-20s:%(lineno)-4s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Rotating JSON file handler (structured, filterable)
    json_handler = logging.handlers.RotatingFileHandler(
        LOG_JSON_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT
    )
    json_handler.setLevel(logging.DEBUG)
    json_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(json_handler)

    # Suppress noisy third-party loggers
    for noisy in ["urllib3", "sqlalchemy.engine", "aiosmtplib", "asyncio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root_logger.info("Logging initialized — logs at %s", LOG_DIR)


def get_logger(name: str) -> ContextAdapter:
    logger = logging.getLogger(name)
    return ContextAdapter(logger, {})
