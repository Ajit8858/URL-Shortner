import random

import validators
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app import crud, schemas
from app.cache import (
    buffer_click,
    get_cached_url,
    invalidate_cache,
    set_cached_url,
    set_negative_cache,
)
from app.config import get_settings
from app.deps import CurrentUser, DbDep, RedisDep, RequiredUser
from app.id_generator import get_id_generator
from app.rate_limiter import client_identifier, enforce_rate_limit
from app.utils import base62_encode, random_fallback_code

router = APIRouter(tags=["urls"])
settings = get_settings()


@router.post(
    "/api/v1/shorten", response_model=schemas.ShortenResponse, status_code=201
)
async def shorten_url(
    payload: schemas.ShortenRequest,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    current_user: CurrentUser,
):
    identifier = client_identifier(request, str(current_user.id) if current_user else None)
    limit = (
        settings.RATE_LIMIT_AUTH_PER_MIN
        if current_user
        else settings.RATE_LIMIT_ANON_PER_MIN
    )
    await enforce_rate_limit(request, redis, identifier, limit)

    long_url = str(payload.long_url)
    if not validators.url(long_url):
        raise HTTPException(status_code=400, detail="Invalid URL")

    is_custom = payload.custom_alias is not None

    url_id: int | None = None

    if is_custom:
        if len(payload.custom_alias) > settings.CUSTOM_ALIAS_MAX_LENGTH:
            raise HTTPException(status_code=400, detail="Alias too long")
        existing = await crud.get_url_by_alias(db, payload.custom_alias)
        if existing:
            raise HTTPException(status_code=409, detail="Alias already taken")
        short_code = payload.custom_alias
        # Custom aliases still need a distributed numeric primary key.
        try:
            url_id = await get_id_generator(redis).next_id()
        except Exception:
            url_id = None
    else:
        try:
            generator = get_id_generator(redis)
            url_id = await generator.next_id()
            short_code = base62_encode(url_id)
        except Exception:
            # Redis unavailable: degrade gracefully instead of failing writes.
            short_code = random_fallback_code()
            url_id = None

    if url_id is None:
        # Fallback path with no distributed counter available.
        url_id = random.randint(10**12, 10**15)

    url = await crud.create_url(
        db,
        url_id=url_id,
        short_code=short_code,
        long_url=long_url,
        owner_id=str(current_user.id) if current_user else None,
        is_custom_alias=is_custom,
        expires_in_days=payload.expires_in_days,
    )

    await set_cached_url(redis, url.short_code, url.long_url)

    base_url = str(request.base_url).rstrip("/")
    short_url = f"{base_url}/{url.short_code}"

    return schemas.ShortenResponse(
        short_code=url.short_code,
        short_url=short_url,
        long_url=url.long_url,
        created_at=url.created_at,
        expires_at=url.expires_at,
    )


@router.get("/short.ly/{short_code}", status_code=status.HTTP_302_FOUND)
async def redirect_short_url(short_code: str, db: DbDep, redis: RedisDep):
    """
    Hot path. Order of operations is chosen to minimize p99 latency and
    Postgres load at scale:
      1. Redis cache lookup (sub-millisecond, handles ~majority of traffic
         once warm).
      2. On miss, Postgres lookup + populate cache for next time.
      3. Click counting is buffered in Redis, never synchronous with the
         redirect itself.
    """
    cached = await get_cached_url(redis, short_code)
    if cached is not None:
        if cached == "__NOT_FOUND__":
            raise HTTPException(status_code=404, detail="Short URL not found")
        await buffer_click(redis, short_code)
        return RedirectResponse(url=cached, status_code=status.HTTP_302_FOUND)

    url = await crud.get_url_by_code(db, short_code)
    if url is None:
        await set_negative_cache(redis, short_code)
        raise HTTPException(status_code=404, detail="Short URL not found")

    await set_cached_url(redis, short_code, url.long_url)
    await buffer_click(redis, short_code)
    return RedirectResponse(url=url.long_url, status_code=status.HTTP_302_FOUND)


@router.get("/api/v1/urls", response_model=list[schemas.URLStats])
async def list_user_urls(db: DbDep, current_user: RequiredUser):
    urls = await crud.list_user_urls(db, str(current_user.id))
    response = []
    for url in urls:
        response.append(
            schemas.URLStats(
                short_code=url.short_code,
                long_url=url.long_url,
                click_count=url.click_count,
                created_at=url.created_at,
                is_active=url.is_active,
            )
        )
    return response


@router.get("/api/v1/urls/{short_code}/stats", response_model=schemas.URLStats)
async def get_stats(
    short_code: str,
    db: DbDep,
    redis: RedisDep,
    current_user: RequiredUser,
):
    url = await crud.get_url_by_code(db, short_code)
    if url is None or str(url.owner_id) != str(current_user.id):
        raise HTTPException(status_code=404, detail="Short URL not found or not owned by you")

    buffered = await redis.get(f"clicks:{short_code}")
    total_clicks = url.click_count + (int(buffered) if buffered else 0)

    return schemas.URLStats(
        short_code=url.short_code,
        long_url=url.long_url,
        click_count=total_clicks,
        created_at=url.created_at,
        is_active=url.is_active,
    )


@router.delete("/api/v1/urls/{short_code}", status_code=204)
async def delete_url(short_code: str, db: DbDep, redis: RedisDep, current_user: RequiredUser):
    deleted = await crud.deactivate_url(db, short_code, str(current_user.id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Short URL not found or not owned by you")
    await invalidate_cache(redis, short_code)
    return Response(status_code=204)
