import asyncio
from typing import Optional

import httpx
import structlog

from ..config import settings
from ..models import Post
from .base import BaseProvider, ProviderError

logger = structlog.get_logger()

GRAPH_API_BASE = "https://graph.facebook.com/v18.0"
INSTAGRAM_API_BASE = "https://graph.instagram.com/v18.0"

# Metric sets to try in order — the API supports different metrics depending
# on the token type (IG vs FB), media type, and API version.
METRIC_SETS = [
    # New Instagram Business API (IG tokens)
    "reach,likes,comments,shares,saved,total_interactions",
    # Legacy Facebook Graph API (FB page tokens) — images/carousels
    "impressions,reach,likes,comments,shares,saved",
    # Reels-specific
    "plays,reach,likes,comments,shares,saved",
    # Minimal fallback
    "reach,likes,comments",
]


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

    def _api_base(self) -> str:
        if settings.instagram_access_token.startswith("IG"):
            return INSTAGRAM_API_BASE
        return GRAPH_API_BASE

    async def fetch_metrics(self, post: Post) -> Optional[dict]:
        media_id = post.platform_post_id
        if not media_id:
            return None

        api_base = self._api_base()

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                # Try each metric set until one works
                resp = None
                used_metrics = None
                for metrics_list in METRIC_SETS:
                    resp = await self._request_with_retry(
                        client,
                        f"{api_base}/{media_id}/insights",
                        params={
                            "metric": metrics_list,
                            "access_token": settings.instagram_access_token,
                        },
                    )
                    if resp.status_code == 200:
                        used_metrics = metrics_list
                        break
                    # If it's a "posted before business conversion" error, don't retry
                    if resp.status_code == 400:
                        body = resp.text
                        if "converted to a business account" in body:
                            logger.warning(
                                "instagram.pre_business_post",
                                service="collector",
                                platform="instagram",
                                post_id=media_id,
                            )
                            return None

                if not resp or resp.status_code != 200:
                    raise ProviderError(
                        self.platform, media_id,
                        f"API returned {resp.status_code}: {resp.text[:200]}",
                    )

                insights_data = resp.json().get("data", [])
                metrics_map = {}
                for item in insights_data:
                    name = item.get("name", "")
                    values = item.get("values", [])
                    if values:
                        metrics_map[name] = values[0].get("value")
                    elif "total_value" in item:
                        metrics_map[name] = item["total_value"].get("value")

                is_reel = self._is_reel(post)
                result = {
                    "impressions": metrics_map.get("impressions") or metrics_map.get("total_interactions"),
                    "reach": metrics_map.get("reach"),
                    "likes": metrics_map.get("likes"),
                    "comments": metrics_map.get("comments"),
                    "shares": metrics_map.get("shares"),
                    "saves": metrics_map.get("saved"),
                    "raw": {"insights": insights_data, "is_reel": is_reel, "metrics_used": used_metrics},
                }

                if is_reel:
                    result["video_views"] = metrics_map.get("plays") or metrics_map.get("ig_reels_video_view_total_count")

                return result

            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(self.platform, media_id, str(exc)) from exc
