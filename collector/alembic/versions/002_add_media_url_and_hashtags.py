"""Add media_url to posts and post_hashtags table

Revision ID: 002
Revises: 001
Create Date: 2026-04-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("media_url", sa.Text(), nullable=True),
        schema="analytics",
    )

    op.create_table(
        "post_hashtags",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("analytics.posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hashtag", sa.String(), nullable=False),
        sa.UniqueConstraint("post_id", "hashtag", name="uq_post_hashtag"),
        schema="analytics",
    )

    op.create_index(
        "ix_post_hashtags_hashtag",
        "post_hashtags",
        ["hashtag"],
        schema="analytics",
    )


def downgrade() -> None:
    op.drop_table("post_hashtags", schema="analytics")
    op.drop_column("posts", "media_url", schema="analytics")
