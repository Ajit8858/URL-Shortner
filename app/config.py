"""
Centralized, environment-driven configuration.
Every value can be overridden by an env var so the same image runs in
dev / staging / prod without code changes (12-factor config).
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    APP_NAME: str = "URL Shortener"
    ENV: str = "production"
    BASE_URL: str = "https://short.ly"
    SECRET_KEY: str = "change-me-in-production-use-a-real-secret"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # --- Database (Postgres, async, pooled) ---
    # In production this points at PgBouncer (transaction pooling) which
    # sits in front of a primary + read replicas.
    DATABASE_URL: str = (
        "postgresql+asyncpg://shortener:shortener@localhost:5432/shortener"
    )
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 1800  # seconds

    # --- Redis (cache + counters + rate limiting) ---
    # Point this at a Redis Cluster endpoint in production.
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_TTL_SECONDS: int = 3600          # hot URL cache
    NEGATIVE_CACHE_TTL_SECONDS: int = 60   # cache "not found" to stop hot-key abuse

    # --- ID generation ---
    # Each app instance reserves a batch of IDs from Redis at once,
    # then hands them out locally -> O(1) amortized Redis round trips.
    ID_BATCH_SIZE: int = 1000
    WORKER_ID: int = 1  # override per-instance via env in k8s/ecs

    # --- Short code ---
    SHORT_CODE_MIN_LENGTH: int = 6
    CUSTOM_ALIAS_MAX_LENGTH: int = 30

    # --- Rate limiting (sliding window, per IP or API key) ---
    RATE_LIMIT_ANON_PER_MIN: int = 20
    RATE_LIMIT_AUTH_PER_MIN: int = 120

    # --- Pagination ---
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
