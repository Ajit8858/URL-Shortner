"""
Cache-aside layer sitting in front of Postgres for the redirect hot path.

Design:
  - GET /{code}: check Redis first. On hit, return immediately (sub-ms,
    no DB round trip). On miss, read Postgres, populate cache, return.
  - Negative caching: nonexistent codes are cached too (short TTL) so a
    burst of requests for a bad/typo'd code can't hammer Postgres
    (protects against scraping / enumeration abuse).
  - Click counts are NOT incremented synchronously in Postgres on every
    redirect (that would recreate the bottleneck we're avoiding).
    Instead they're buffered in Redis (INCR) and flushed to Postgres by
    a periodic background task / worker -> write amplification stays
    off the hot path.
"""
from redis.asyncio import Redis, ConnectionPool

from app.config import get_settings

settings = get_settings()

_NEGATIVE_SENTINEL = "__NOT_FOUND__"

_pool: ConnectionPool | None = None


def get_redis_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.REDIS_URL, decode_responses=True, max_connections=100
        )
    return _pool


def get_redis() -> Redis:
    return Redis(connection_pool=get_redis_pool())


def _url_key(short_code: str) -> str:
    return f"url:{short_code}"


def _clicks_key(short_code: str) -> str:
    return f"clicks:{short_code}"


async def get_cached_url(redis: Redis, short_code: str) -> str | None:
    value = await redis.get(_url_key(short_code))
    if value == _NEGATIVE_SENTINEL:
        return _NEGATIVE_SENTINEL
    return value


async def set_cached_url(redis: Redis, short_code: str, long_url: str) -> None:
    await redis.set(_url_key(short_code), long_url, ex=settings.CACHE_TTL_SECONDS)


async def set_negative_cache(redis: Redis, short_code: str) -> None:
    await redis.set(
        _url_key(short_code),
        _NEGATIVE_SENTINEL,
        ex=settings.NEGATIVE_CACHE_TTL_SECONDS,
    )


async def invalidate_cache(redis: Redis, short_code: str) -> None:
    await redis.delete(_url_key(short_code))


async def buffer_click(redis: Redis, short_code: str) -> None:
    """O(1) increment; a background worker periodically flushes these
    deltas into Postgres `urls.click_count` and `click_events`."""
    await redis.incr(_clicks_key(short_code))
