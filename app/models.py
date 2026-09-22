import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    api_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    urls: Mapped[list["URL"]] = relationship(back_populates="owner")


class URL(Base):
    """
    Core entity. `id` is a 64-bit distributed ID (see app/id_generator.py),
    NOT a plain DB auto-increment, so ID generation is never a single
    point of contention as write volume grows across many app replicas.
    """

    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    short_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    long_url: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    is_custom_alias: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    click_count: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    owner: Mapped["User | None"] = relationship(back_populates="urls")

    __table_args__ = (
        Index("ix_urls_owner_created", "owner_id", "created_at"),
    )


class ClickEvent(Base):
    """
    Append-only click log for analytics. Written asynchronously (fire and
    forget / via a background task or queue) so it never sits on the
    critical redirect path's latency.

    At very high scale this table is the first candidate to move out of
    Postgres entirely (e.g. into Kafka -> ClickHouse) since it is
    write-heavy, time-series shaped, and not needed for the redirect
    itself.
    """

    __tablename__ = "click_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    url_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("urls.id"), index=True
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)

    __table_args__ = (
        Index("ix_click_events_url_time", "url_id", "clicked_at"),
    )
