"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-22
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("api_key", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_api_key", "users", ["api_key"], unique=True)

    op.create_table(
        "urls",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=False),
        sa.Column("short_code", sa.String(32), nullable=False),
        sa.Column("long_url", sa.Text, nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_custom_alias", sa.Boolean, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("click_count", sa.BigInteger, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_urls_short_code", "urls", ["short_code"], unique=True)
    op.create_index("ix_urls_owner_id", "urls", ["owner_id"])
    op.create_index("ix_urls_created_at", "urls", ["created_at"])
    op.create_index("ix_urls_owner_created", "urls", ["owner_id", "created_at"])

    op.create_table(
        "click_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("url_id", sa.BigInteger, sa.ForeignKey("urls.id"), nullable=False),
        sa.Column("clicked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ip_address", postgresql.INET, nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("referrer", sa.String(512), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
    )
    op.create_index("ix_click_events_url_id", "click_events", ["url_id"])
    op.create_index("ix_click_events_clicked_at", "click_events", ["clicked_at"])
    op.create_index("ix_click_events_url_time", "click_events", ["url_id", "clicked_at"])


def downgrade() -> None:
    op.drop_table("click_events")
    op.drop_table("urls")
    op.drop_table("users")
