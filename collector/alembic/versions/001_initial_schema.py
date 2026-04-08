"""Initial analytics schema

Revision ID: 001
Revises:
Create Date: 2026-04-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS analytics")

    op.create_table(
        "posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("postiz_post_id", sa.String(), nullable=True),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("platform_post_id", sa.String(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("media_type", sa.String(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("platform", "platform_post_id", name="uq_platform_post"),
        schema="analytics",
    )

    op.create_table(
        "post_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analytics.posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=True),
        sa.Column("reach", sa.BigInteger(), nullable=True),
        sa.Column("likes", sa.BigInteger(), nullable=True),
        sa.Column("comments", sa.BigInteger(), nullable=True),
        sa.Column("shares", sa.BigInteger(), nullable=True),
        sa.Column("saves", sa.BigInteger(), nullable=True),
        sa.Column("clicks", sa.BigInteger(), nullable=True),
        sa.Column("video_views", sa.BigInteger(), nullable=True),
        sa.Column("video_watch_time_ms", sa.BigInteger(), nullable=True),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        schema="analytics",
    )

    op.create_index(
        "ix_post_metrics_post_id_synced",
        "post_metrics",
        ["post_id", "synced_at"],
        schema="analytics",
    )

    op.create_table(
        "sync_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("platform", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("posts_synced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("posts_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_table("sync_log", schema="analytics")
    op.drop_table("post_metrics", schema="analytics")
    op.drop_table("posts", schema="analytics")
