"""Parse hashtags from post content and sync them to the post_hashtags table."""

import re

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Post, PostHashtag

logger = structlog.get_logger()

HASHTAG_PATTERN = re.compile(r"#(\w+)", re.UNICODE)


def extract_hashtags(text: str | None) -> list[str]:
    """Extract unique lowercase hashtags from text."""
    if not text:
        return []
    return sorted(set(tag.lower() for tag in HASHTAG_PATTERN.findall(text)))


async def sync_post_hashtags(session: AsyncSession, post: Post) -> int:
    """Parse hashtags from post content and upsert into post_hashtags. Returns count added."""
    tags = extract_hashtags(post.content_text)
    if not tags:
        return 0

    added = 0
    for tag in tags:
        stmt = (
            pg_insert(PostHashtag)
            .values(post_id=post.id, hashtag=tag)
            .on_conflict_do_nothing(constraint="uq_post_hashtag")
        )
        result = await session.execute(stmt)
        if result.rowcount and result.rowcount > 0:
            added += 1

    return added
