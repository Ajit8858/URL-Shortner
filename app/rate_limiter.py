"""
Distributed rate limiting using Redis, so limits are enforced correctly
across ALL app replicas (not per-process, which would let users bypass
limits by hitting different instances behind the load balancer).

Uses a fixed-window counter (simple, cheap, one Redis round trip) which
is sufficiently accurate for abuse protection at this scale. Swap for a
sliding-window-log or token-bucket (e.g. via a Lua script) if stricter
smoothing is required.
"""
import time

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis

from app.config import get_settings

settings = get_settings()


async def enforce_rate_limit(
    request: Request, redis: Redis, identifier: str, limit_per_min: int
) -> None:
    window = int(time.time() // 60)
    key = f"ratelimit:{identifier}:{window}"

    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, 65)
        count, _ = await pipe.execute()

    if count > limit_per_min:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please slow down.",
            headers={"Retry-After": "60"},
        )


def client_identifier(request: Request, user_id: str | None) -> str:
    if user_id:
        return f"user:{user_id}"
    # Behind a load balancer, trust X-Forwarded-For (set by the LB, not
    # the client) rather than request.client.host.
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else request.client.host
    return f"ip:{ip}"
