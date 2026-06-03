from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "PortalBackend"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database (PostgreSQL)
    DATABASE_URL: str = ""

    # JWT
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Email Verification Token
    EMAIL_VERIFY_TOKEN_EXPIRE_HOURS: int = 24

    # Frontend URL
    FRONTEND_URL: str = "https://localhost:4200"

    # Zavudev (Zavu) Email
    ZAVUDEV_API_KEY: str = ""
    ZAVU_SENDER_EMAIL: str = "no-reply@arinedge.com"

    # Upstox
    UPSTOX_ACCESS_TOKEN: str = ""

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    REDIS_CACHE_TTL: int = 300  # 5 minutes default

    # Graph Pipeline
    GRAPH_PIPELINE_ENABLED: bool = True
    GRAPH_PIPELINE_INITIAL_DELAY_SECONDS: int = 600  # 10 min before first run

    # Logging
    LOG_LEVEL: str = "DEBUG"
    LOG_DIR: str = "logs"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_COUNT: int = 30

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
