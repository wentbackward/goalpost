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
from sqlalchemy import text
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
# DB mode — queries Postiz's Prisma-managed tables directly
# ---------------------------------------------------------------------------
def _extract_platform_post_id(release_url: str | None, provider: str) -> str | None:
    """Extract the platform-native post ID from Postiz's releaseURL."""
    if not release_url:
        return None
    # Twitter/X: https://twitter.com/.../status/123 or https://x.com/.../status/123
    if provider in ("x", "twitter"):
        parts = release_url.rstrip("/").split("/")
        if "status" in parts:
            return parts[parts.index("status") + 1]
    # Instagram: shortcode extracted here, resolved to numeric ID later
    if provider == "instagram":
        parts = release_url.rstrip("/").split("/")
        if parts:
            return f"shortcode:{parts[-1]}"
    # Facebook: https://www.facebook.com/reel/123
    if provider == "facebook":
        parts = release_url.rstrip("/").split("/")
        if parts:
            return parts[-1]
    # YouTube: https://www.youtube.com/watch?v=ABC or https://youtu.be/ABC
    if provider == "youtube":
        if "v=" in release_url:
            return release_url.split("v=")[1].split("&")[0]
        parts = release_url.rstrip("/").split("/")
        if parts:
            return parts[-1]
    # LinkedIn: various formats
    if provider == "linkedin":
        parts = release_url.rstrip("/").split("/")
        if parts:
            return parts[-1]
    return release_url


async def _resolve_ig_shortcodes(posts: list["PostizPost"]) -> None:
    """Resolve Instagram shortcodes to numeric media IDs via the Graph API."""
    if not settings.instagram_access_token or not settings.instagram_business_account_id:
        return

    # Collect shortcodes that need resolution
    shortcode_posts = [
        p for p in posts
        if p.platform == "instagram" and p.platform_post_id.startswith("shortcode:")
    ]
    if not shortcode_posts:
        return

    shortcode_map: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            url = f"https://graph.facebook.com/v18.0/{settings.instagram_business_account_id}/media"
            params = {
                "fields": "id,shortcode",
                "limit": 50,
                "access_token": settings.instagram_access_token,
            }
            # Paginate until we've found all shortcodes or run out of pages
            needed = {p.platform_post_id.split(":", 1)[1] for p in shortcode_posts}
            while needed:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    logger.warning(
                        "postiz_bridge.ig_shortcode_resolve_failed",
                        service="collector",
                        status=resp.status_code,
                    )
                    break
                data = resp.json()
                for item in data.get("data", []):
                    sc = item.get("shortcode", "")
                    if sc in needed:
                        shortcode_map[sc] = item["id"]
                        needed.discard(sc)
                next_url = data.get("paging", {}).get("next")
                if not next_url or not needed:
                    break
                url = next_url
                params = {}
    except Exception as exc:
        logger.error("postiz_bridge.ig_shortcode_error", service="collector", error=str(exc))

    # Apply resolved IDs
    for p in shortcode_posts:
        sc = p.platform_post_id.split(":", 1)[1]
        if sc in shortcode_map:
            p.platform_post_id = shortcode_map[sc]
        else:
            logger.warning(
                "postiz_bridge.ig_shortcode_unresolved",
                service="collector",
                shortcode=sc,
            )
            p.platform_post_id = sc  # Fall back to shortcode


def _strip_html(html: str | None) -> str | None:
    """Remove HTML tags from Postiz content (stored as HTML)."""
    if not html:
        return None
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


async def _get_posts_from_db(since: datetime) -> list[PostizPost]:
    """Query Postiz's public."Post" + "Integration" tables directly."""
    db_url = settings.collector_database_url
    engine = create_async_engine(db_url, echo=False)

    query = text("""
        SELECT
            p."id",
            p."content",
            p."publishDate",
            p."releaseURL",
            p."state",
            i."providerIdentifier" AS provider
        FROM public."Post" p
        JOIN public."Integration" i ON i."id" = p."integrationId"
        WHERE p."state" = 'PUBLISHED'
          AND p."releaseURL" IS NOT NULL
          AND p."publishDate" >= :since
        ORDER BY p."publishDate" DESC
    """)

    platform_map = {
        "x": "twitter", "twitter": "twitter",
        "linkedin": "linkedin",
        "instagram": "instagram",
        "facebook": "facebook",
        "youtube": "youtube",
        "tiktok": "tiktok",
    }

    posts: list[PostizPost] = []
    # Postiz publishDate is timezone-naive; strip tzinfo for asyncpg compat
    since_naive = since.replace(tzinfo=None)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(query, {"since": since_naive})
            for row in result.mappings():
                provider = str(row["provider"]).lower()
                platform = platform_map.get(provider, provider)
                platform_post_id = _extract_platform_post_id(row["releaseURL"], provider)
                if not platform_post_id:
                    continue

                pub_date = row["publishDate"]
                if pub_date and pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)

                posts.append(PostizPost(
                    postiz_id=str(row["id"]),
                    platform=platform,
                    platform_post_id=platform_post_id,
                    content=_strip_html(row["content"]),
                    published_at=pub_date,
                ))

        logger.info(
            "postiz_bridge.db_query_ok",
            service="collector",
            posts_found=len(posts),
        )
    except Exception as exc:
        logger.error("postiz_bridge.db_query_failed", service="collector", error=str(exc))
    finally:
        await engine.dispose()

    await _resolve_ig_shortcodes(posts)
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
            .on_conflict_do_update(
                constraint="uq_platform_post",
                set_={
                    "content_text": pp.content,
                    "published_at": pp.published_at,
                    "postiz_post_id": pp.postiz_id,
                    "updated_at": datetime.now(timezone.utc),
                },
                where=Post.content_text.is_(None) | Post.published_at.is_(None),
            )
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
