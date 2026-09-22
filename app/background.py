"""
Periodic worker that drains Redis click-count buffers into Postgres.

Keeping this off the request path is what lets the redirect endpoint
stay cheap (one Redis INCR) even at very high click volume: writes to
Postgres are batched every FLUSH_INTERVAL_SECONDS instead of once per
click.

In production this can run as:
  - a background asyncio task inside one designated app replica, or
    (simpler, shown here)
  - a small standalone worker process/deployment (recommended once you
    have more than a couple of app replicas, so flushing isn't tied to
    web instance lifecycle).
"""
import asyncio
import logging

from app.cache import get_redis
from app.crud import flush_click_delta
from app.database import AsyncSessionLocal

logger = logging.getLogger("click_flusher")

FLUSH_INTERVAL_SECONDS = 15


async def flush_click_buffers_once() -> int:
    redis = get_redis()
    keys = [key async for key in redis.scan_iter(match="clicks:*")]
    flushed = 0

    for key in keys:
        short_code = key.split(":", 1)[1]
        # Atomically read-and-reset the counter so concurrent clicks
        # during the flush aren't lost.
        delta = await redis.getdel(key)
        if not delta:
            continue
        delta = int(delta)
        async with AsyncSessionLocal() as db:
            await flush_click_delta(db, short_code, delta)
        flushed += 1

    return flushed


async def run_click_flusher_forever() -> None:
    while True:
        try:
            count = await flush_click_buffers_once()
            if count:
                logger.info("Flushed click deltas for %d short codes", count)
        except Exception:
            logger.exception("Click flush cycle failed")
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
