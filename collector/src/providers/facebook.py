import asyncio
from typing import Optional

import httpx
import structlog

from ..config import settings
from ..models import Post
from .base import BaseProvider, ProviderError

logger = structlog.get_logger()

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"

METRIC_SETS = [
    # Regular page posts
    "post_impressions,post_impressions_unique,post_reactions_like_total,post_comments,post_shares,post_clicks,post_video_views,post_video_avg_time_watched",
    # Reels / video posts
    "post_impressions,post_impressions_unique,post_reactions_like_total,post_video_views",
    # Minimal fallback
    "post_impressions,post_impressions_unique",
]


class FacebookProvider(BaseProvider):
    platform = "facebook"

    async def is_configured(self) -> bool:
        return bool(settings.facebook_access_token and settings.facebook_page_id)

    async def _request_with_retry(
        self, client: httpx.AsyncClient, url: str, params: dict
    ) -> httpx.Response:
        for attempt in range(4):
            resp = await client.get(url, params=params)
            if resp.status_code != 429:
                return resp
            if attempt < 3:
                wait = 2 ** attempt
                logger.warning("facebook.rate_limited", attempt=attempt, wait_seconds=wait)
                await asyncio.sleep(wait)
        return resp

    async def _fetch_basic_metrics(
        self, client: httpx.AsyncClient, post_id: str
    ) -> Optional[dict]:
        """Fallback for Reels/posts that don't support insights endpoint."""
        resp = await self._request_with_retry(
            client,
            f"{GRAPH_API_BASE}/{post_id}",
            params={
                "fields": "shares,likes.summary(true),comments.summary(true)",
                "access_token": settings.facebook_access_token,
            },
        )
        if resp.status_code != 200:
            raise ProviderError(
                self.platform, post_id,
                f"API returned {resp.status_code}: {resp.text[:200]}",
            )
        data = resp.json()
        return {
            "likes": data.get("likes", {}).get("summary", {}).get("total_count"),
            "comments": data.get("comments", {}).get("summary", {}).get("total_count"),
            "shares": data.get("shares", {}).get("count"),
            "raw": {"basic_fields": data, "fallback": True},
        }

    async def fetch_metrics(self, post: Post) -> Optional[dict]:
        post_id = post.platform_post_id
        if not post_id:
            return None

        # Ensure full post ID format: page_id_post_id
        if "_" not in post_id:
            post_id = f"{settings.facebook_page_id}_{post_id}"

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = None
                for metrics_list in METRIC_SETS:
                    resp = await self._request_with_retry(
                        client,
                        f"{GRAPH_API_BASE}/{post_id}/insights",
                        params={
                            "metric": metrics_list,
                            "access_token": settings.facebook_access_token,
                        },
                    )
                    if resp.status_code == 200:
                        break

                if not resp or resp.status_code != 200:
                    # Reels don't support insights — fall back to basic fields
                    return await self._fetch_basic_metrics(client, post_id)

                insights_data = resp.json().get("data", [])
                metrics_map = {}
                for item in insights_data:
                    name = item.get("name", "")
                    values = item.get("values", [])
                    if values:
                        metrics_map[name] = values[0].get("value")

                # Convert avg watch time (seconds) to milliseconds
                avg_watch_time = metrics_map.get("post_video_avg_time_watched")
                watch_time_ms = int(avg_watch_time * 1000) if avg_watch_time else None

                return {
                    "impressions": metrics_map.get("post_impressions"),
                    "reach": metrics_map.get("post_impressions_unique"),
                    "likes": metrics_map.get("post_reactions_like_total"),
                    "comments": metrics_map.get("post_comments"),
                    "shares": metrics_map.get("post_shares"),
                    "clicks": metrics_map.get("post_clicks"),
                    "video_views": metrics_map.get("post_video_views"),
                    "video_watch_time_ms": watch_time_ms,
                    "raw": {"insights": insights_data},
                }

            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(self.platform, post_id, str(exc)) from exc
