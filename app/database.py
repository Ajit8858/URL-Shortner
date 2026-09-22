"""
Async DB session management.

Scaling notes:
- Uses SQLAlchemy's async engine with a bounded connection pool per app
  process. With N app replicas x DB_POOL_SIZE connections, size PgBouncer
  (transaction-mode pooling) in front of Postgres so the DB itself only
  ever sees a small, stable number of real connections.
- Read-heavy endpoints (redirect lookups) should mostly be served from
  Redis cache (see cache.py) so Postgres mainly absorbs writes + cache
  misses, which is what lets this design scale to millions of users on
  a modest primary + a couple of read replicas.
"""
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,   # avoid stale-connection errors after failover
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, class_=AsyncSession
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
