from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import models


async def get_url_by_code(db: AsyncSession, short_code: str) -> models.URL | None:
    result = await db.execute(
        select(models.URL).where(
            models.URL.short_code == short_code, models.URL.is_active.is_(True)
        )
    )
    return result.scalar_one_or_none()


async def get_url_by_alias(db: AsyncSession, alias: str) -> models.URL | None:
    result = await db.execute(select(models.URL).where(models.URL.short_code == alias))
    return result.scalar_one_or_none()


async def create_url(
    db: AsyncSession,
    *,
    url_id: int,
    short_code: str,
    long_url: str,
    owner_id: str | None,
    is_custom_alias: bool,
    expires_in_days: int | None,
) -> models.URL:
    expires_at = None
    if expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    url = models.URL(
        id=url_id,
        short_code=short_code,
        long_url=long_url,
        owner_id=owner_id,
        is_custom_alias=is_custom_alias,
        expires_at=expires_at,
    )
    db.add(url)
    await db.commit()
    await db.refresh(url)
    return url


async def deactivate_url(db: AsyncSession, short_code: str, owner_id: str) -> bool:
    result = await db.execute(
        update(models.URL)
        .where(models.URL.short_code == short_code, models.URL.owner_id == owner_id)
        .values(is_active=False)
    )
    await db.commit()
    return result.rowcount > 0


async def flush_click_delta(db: AsyncSession, short_code: str, delta: int) -> None:
    """Applied periodically by the background flusher, not per-request."""
    await db.execute(
        update(models.URL)
        .where(models.URL.short_code == short_code)
        .values(click_count=models.URL.click_count + delta)
    )
    await db.commit()


async def get_user_by_email(db: AsyncSession, email: str) -> models.User | None:
    result = await db.execute(select(models.User).where(models.User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> models.User | None:
    result = await db.execute(select(models.User).where(models.User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_api_key(db: AsyncSession, api_key: str) -> models.User | None:
    result = await db.execute(
        select(models.User).where(models.User.api_key == api_key)
    )
    return result.scalar_one_or_none()


async def list_user_urls(db: AsyncSession, owner_id: str) -> list[models.URL]:
    result = await db.execute(
        select(models.URL)
        .where(models.URL.owner_id == owner_id, models.URL.is_active.is_(True))
        .order_by(models.URL.created_at.desc())
    )
    return list(result.scalars().all())


async def create_user(
    db: AsyncSession, *, email: str, hashed_password: str, api_key: str
) -> models.User:
    user = models.User(email=email, hashed_password=hashed_password, api_key=api_key)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
