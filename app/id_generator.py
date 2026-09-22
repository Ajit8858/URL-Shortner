"""
Distributed, collision-free ID generation for short codes.

Why not just `SERIAL` / DB auto-increment?
  At high write concurrency across many app replicas, a single DB
  sequence becomes a contention point and ties ID generation to DB
  availability. Instead we use **batched counter allocation**:

    1. Each app process asks Redis (`INCRBY`) for a block of N IDs
       (ID_BATCH_SIZE) at once -> ONE Redis round trip per N requests.
    2. IDs are handed out from an in-memory range until exhausted, then
       the process fetches the next block.
    3. The result is Base62-encoded into a short, URL-safe code.

This is the same "range handle" pattern used by systems like Flickr's
ticket servers and many production URL shorteners. It gives:
  - No collisions (Redis INCRBY is atomic).
  - Very low latency (amortized ~0 network calls per short-code mint).
  - No dependency on Postgres for the hot write path.
  - Horizontal scale: adding more app replicas just means more
    independent local ranges, not more contention.

If Redis is unavailable, the counter falls back to a UUID-derived
Base62 code (see utils.py) so writes degrade gracefully instead of
failing outright.
"""
import asyncio

from redis.asyncio import Redis

from app.config import get_settings
from app.utils import base62_encode

settings = get_settings()

_COUNTER_KEY = "url_shortener:id_counter"


class BatchIdGenerator:
    def __init__(self, redis: Redis, batch_size: int = settings.ID_BATCH_SIZE):
        self._redis = redis
        self._batch_size = batch_size
        self._current: int = 0
        self._max: int = 0
        self._lock = asyncio.Lock()

    async def _reserve_new_block(self) -> None:
        # Atomically reserve the next `batch_size` IDs for this process.
        new_max = await self._redis.incrby(_COUNTER_KEY, self._batch_size)
        self._max = new_max
        self._current = new_max - self._batch_size

    async def next_id(self) -> int:
        async with self._lock:
            if self._current >= self._max:
                await self._reserve_new_block()
            self._current += 1
            return self._current

    async def next_short_code(self) -> str:
        raw_id = await self.next_id()
        return base62_encode(raw_id)


_generator: BatchIdGenerator | None = None


def get_id_generator(redis: Redis) -> BatchIdGenerator:
    global _generator
    if _generator is None:
        _generator = BatchIdGenerator(redis)
    return _generator


# Lua script: only raise the counter, never lower it. This makes seeding
# idempotent and safe to call from multiple app replicas concurrently at
# startup — whichever one sees the highest DB max(id) wins, and nobody
# can accidentally roll the counter backwards.
_RAISE_COUNTER_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or "0")
local floor_value = tonumber(ARGV[1])
if floor_value > current then
    redis.call('SET', KEYS[1], floor_value)
    return floor_value
end
return current
"""


async def seed_counter_floor(redis: Redis, min_value: int) -> int:
    """
    Ensures the Redis ID counter is never below `min_value`.

    Call this at app startup with `min_value = SELECT MAX(id) FROM urls`.
    This is the safety net for the scenario this design is otherwise
    exposed to: Redis is the fast path for ID allocation, but Postgres
    is the durable source of truth. If Redis ever loses the counter key
    (cold restart without AOF/RDB persistence, memory-pressure eviction,
    a failover to a fresh replica, or a manual FLUSHALL) and nothing
    reconciled the two, new IDs would restart near zero and collide
    with existing primary keys — every write fails until fixed by hand.
    Running this on every app startup makes that class of incident
    self-healing instead of a page-worthy outage.
    """
    script = redis.register_script(_RAISE_COUNTER_SCRIPT)
    result = await script(keys=[_COUNTER_KEY], args=[min_value])
    return int(result)
