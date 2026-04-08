import asyncio
from typing import Optional

import httpx
import structlog

from ..config import settings
from ..models import Post
from .base import BaseProvider, ProviderError

logger = structlog.get_logger()

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"

# Standard metrics for images/carousels
STANDARD_METRICS = "impressions,reach,likes,comments,shares,saved"

# Reels use different metric names
REELS_METRICS = "plays,reach,likes,comments,shares,saved"


class InstagramProvider(BaseProvider):
    platform = "instagram"

    async def is_configured(self) -> bool:
        return bool(settings.instagram_access_token and settings.instagram_business_account_id)

    async def _request_with_retry(
        self, client: httpx.AsyncClient, url: str, params: dict
    ) -> httpx.Response:
        for attempt in range(4):
            resp = await client.get(url, params=params)
            if resp.status_code != 429:
                return resp
            if attempt < 3:
                wait = 2 ** attempt
                logger.warning("instagram.rate_limited", attempt=attempt, wait_seconds=wait)
                await asyncio.sleep(wait)
        return resp

    def _is_reel(self, post: Post) -> bool:
        return post.media_type and post.media_type.lower() in ("reel", "video")

    async def fetch_metrics(self, post: Post) -> Optional[dict]:
        media_id = post.platform_post_id
        if not media_id:
            return None

        is_reel = self._is_reel(post)
        metrics_list = REELS_METRICS if is_reel else STANDARD_METRICS

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                # Fetch insights
                resp = await self._request_with_retry(
                    client,
                    f"{GRAPH_API_BASE}/{media_id}/insights",
                    params={
                        "metric": metrics_list,
                        "access_token": settings.instagram_access_token,
                    },
                )

                if resp.status_code != 200:
                    raise ProviderError(
                        self.platform, media_id,
                        f"API returned {resp.status_code}: {resp.text[:200]}",
                    )

                insights_data = resp.json().get("data", [])
                metrics_map = {item["name"]: item["values"][0]["value"] for item in insights_data if item.get("values")}

                result = {
                    "impressions": metrics_map.get("impressions"),
                    "reach": metrics_map.get("reach"),
                    "likes": metrics_map.get("likes"),
                    "comments": metrics_map.get("comments"),
                    "shares": metrics_map.get("shares"),
                    "saves": metrics_map.get("saved"),
                    "raw": {"insights": insights_data, "is_reel": is_reel},
                }

                # For reels, "plays" maps to video_views
                if is_reel:
                    result["video_views"] = metrics_map.get("plays")

                return result

            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(self.platform, media_id, str(exc)) from exc
