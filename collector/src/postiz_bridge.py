"""
Postiz bridge — discovers posts published via Postiz and syncs them
into the analytics.posts table.

Supports two modes controlled by POSTIZ_BRIDGE_MODE:
  - "db"  (default): Direct query against the shared Postgres instance
  - "api": Fallback using the Postiz public API
"""

from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import inspect, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from .config import settings
from .models import Post

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Dataclass-like container returned by both modes
# ---------------------------------------------------------------------------
class PostizPost:
    def __init__(
        self,
        postiz_id: str,
        platform: str,
        platform_post_id: str,
        content: str | None = None,
        media_type: str | None = None,
        published_at: datetime | None = None,
    ):
        self.postiz_id = postiz_id
        self.platform = platform
        self.platform_post_id = platform_post_id
        self.content = content
        self.media_type = media_type
        self.published_at = published_at


# ---------------------------------------------------------------------------
# Schema discovery (DB mode)
# ---------------------------------------------------------------------------
_postiz_columns: dict[str, list[str]] = {}


async def _discover_postiz_schema(engine) -> None:
    """Inspect the public schema to find Postiz tables and columns."""
    global _postiz_columns
    try:
        async with engine.connect() as conn:
            result = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_columns("posts", schema="public")
            )
            cols = [c["name"] for c in result]
            _postiz_columns["posts"] = cols
            logger.info(
                "postiz_bridge.schema_discovered",
                service="collector",
                table="public.posts",
                columns=cols,
            )
    except Exception as exc:
        logger.warning(
            "postiz_bridge.schema_discovery_failed",
            service="collector",
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# DB mode
# ---------------------------------------------------------------------------
async def _get_posts_from_db(since: datetime) -> list[PostizPost]:
    """Query Postiz's public.posts table directly."""
    # Build a sync-compatible URL for the Postiz DB (same Postgres instance)
    db_url = settings.collector_database_url
    engine = create_async_engine(db_url, echo=False)

    if not _postiz_columns:
        await _discover_postiz_schema(engine)

    cols = _postiz_columns.get("posts", [])
    if not cols:
        logger.warning("postiz_bridge.no_schema", service="collector")
        await engine.dispose()
        return []

    # Determine column names — Postiz may use different naming conventions
    id_col = "id"
    # Look for the platform post ID column
    platform_id_col = None
    for candidate in ["platformPostId", "platform_post_id", "externalId", "external_id", "postId"]:
        if candidate in cols:
            platform_id_col = candidate
            break

    platform_col = None
    for candidate in ["platform", "integration", "socialProvider", "social_provider", "type"]:
        if candidate in cols:
            platform_col = candidate
            break

    content_col = None
    for candidate in ["content", "text", "body", "caption", "description"]:
        if candidate in cols:
            content_col = candidate
            break

    published_col = None
    for candidate in ["publishDate", "publish_date", "publishedAt", "published_at", "createdAt", "created_at"]:
        if candidate in cols:
            published_col = candidate
            break

    if not platform_id_col or not platform_col:
        logger.warning(
            "postiz_bridge.missing_columns",
            service="collector",
            available=cols,
            message="Cannot find platform or platform_post_id columns in Postiz posts table",
        )
        await engine.dispose()
        return []

    # Build a safe query using the discovered column names
    select_cols = [f'"{id_col}"', f'"{platform_col}"', f'"{platform_id_col}"']
    if content_col:
        select_cols.append(f'"{content_col}"')
    if published_col:
        select_cols.append(f'"{published_col}"')

    query = f"""
        SELECT {', '.join(select_cols)}
        FROM public.posts
        WHERE "{platform_id_col}" IS NOT NULL
    """
    if published_col:
        query += f' AND "{published_col}" >= :since'

    posts: list[PostizPost] = []
    try:
        async with engine.connect() as conn:
            if published_col:
                result = await conn.execute(text(query), {"since": since})
            else:
                result = await conn.execute(text(query))

            for row in result.mappings():
                platform_val = str(row[platform_col]).lower()
                # Normalise platform names
                platform_map = {
                    "x": "twitter", "twitter": "twitter",
                    "linkedin": "linkedin",
                    "instagram": "instagram",
                    "facebook": "facebook",
                    "youtube": "youtube",
                    "tiktok": "tiktok",
                }
                normalised = platform_map.get(platform_val, platform_val)

                posts.append(PostizPost(
                    postiz_id=str(row[id_col]),
                    platform=normalised,
                    platform_post_id=str(row[platform_id_col]),
                    content=row.get(content_col) if content_col else None,
                    published_at=row.get(published_col) if published_col else None,
                ))
    except Exception as exc:
        logger.error("postiz_bridge.db_query_failed", service="collector", error=str(exc))
    finally:
        await engine.dispose()

    return posts


# ---------------------------------------------------------------------------
# API mode
# ---------------------------------------------------------------------------
async def _get_posts_from_api(since: datetime) -> list[PostizPost]:
    """Fallback: use the Postiz public API."""
    if not settings.postiz_api_key:
        logger.warning(
            "postiz_bridge.api_no_key",
            service="collector",
            message="POSTIZ_API_KEY not set; cannot use API bridge mode",
        )
        return []

    posts: list[PostizPost] = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{settings.next_public_backend_url}/public/v1/posts",
                headers={"Authorization": f"Bearer {settings.postiz_api_key}"},
            )
            if resp.status_code != 200:
                logger.warning(
                    "postiz_bridge.api_error",
                    service="collector",
                    status=resp.status_code,
                    body=resp.text[:200],
                )
                return []

            for item in resp.json():
                published = None
                for key in ("publishDate", "published_at", "createdAt"):
                    if item.get(key):
                        try:
                            published = datetime.fromisoformat(item[key].replace("Z", "+00:00"))
                        except (ValueError, AttributeError):
                            pass
                        break

                if published and published < since:
                    continue

                platform_post_id = item.get("platformPostId") or item.get("externalId")
                if not platform_post_id:
                    continue

                posts.append(PostizPost(
                    postiz_id=str(item.get("id", "")),
                    platform=str(item.get("platform", item.get("socialProvider", ""))).lower(),
                    platform_post_id=str(platform_post_id),
                    content=item.get("content") or item.get("text"),
                    published_at=published,
                ))
    except Exception as exc:
        logger.error("postiz_bridge.api_request_failed", service="collector", error=str(exc))

    return posts


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
async def get_published_posts(since: datetime) -> list[PostizPost]:
    """Return posts published since the given timestamp."""
    if settings.postiz_bridge_mode == "api":
        return await _get_posts_from_api(since)
    return await _get_posts_from_db(since)


async def sync_postiz_posts(session: AsyncSession, since: datetime) -> int:
    """
    Discover posts from Postiz and upsert them into analytics.posts.
    Returns the number of new posts inserted.
    """
    postiz_posts = await get_published_posts(since)
    if not postiz_posts:
        return 0

    inserted = 0
    for pp in postiz_posts:
        stmt = (
            pg_insert(Post)
            .values(
                postiz_post_id=pp.postiz_id,
                platform=pp.platform,
                platform_post_id=pp.platform_post_id,
                content_text=pp.content,
                published_at=pp.published_at,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(constraint="uq_platform_post")
        )
        result = await session.execute(stmt)
        if result.rowcount and result.rowcount > 0:
            inserted += 1

    await session.commit()
    logger.info(
        "postiz_bridge.sync_complete",
        service="collector",
        discovered=len(postiz_posts),
        inserted=inserted,
    )
    return inserted
