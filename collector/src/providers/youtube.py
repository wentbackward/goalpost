import asyncio
from typing import Optional

import httpx
import structlog

from ..config import settings
from ..models import Post
from .base import BaseProvider, ProviderError

logger = structlog.get_logger()

YOUTUBE_DATA_API = "https://www.googleapis.com/youtube/v3"
YOUTUBE_ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class YouTubeProvider(BaseProvider):
    platform = "youtube"

    async def is_configured(self) -> bool:
        return bool(settings.youtube_api_key or settings.youtube_refresh_token)

    def _has_analytics_access(self) -> bool:
        return all([
            settings.youtube_oauth_client_id,
            settings.youtube_oauth_client_secret,
            settings.youtube_refresh_token,
        ])

    async def _get_oauth_token(self, client: httpx.AsyncClient) -> str | None:
        """Exchange refresh token for an access token."""
        if not self._has_analytics_access():
            return None

        try:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.youtube_oauth_client_id,
                    "client_secret": settings.youtube_oauth_client_secret,
                    "refresh_token": settings.youtube_refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if resp.status_code == 200:
                return resp.json().get("access_token")

            logger.warning(
                "youtube.oauth_refresh_failed",
                service="collector",
                platform="youtube",
                status=resp.status_code,
                body=resp.text[:200],
            )
            return None
        except Exception as exc:
            logger.warning(
                "youtube.oauth_refresh_error",
                service="collector",
                platform="youtube",
                error=str(exc),
            )
            return None

    async def _request_with_retry(
        self, client: httpx.AsyncClient, url: str, params: dict, headers: dict | None = None,
    ) -> httpx.Response:
        for attempt in range(4):
            resp = await client.get(url, params=params, headers=headers or {})
            if resp.status_code != 429:
                return resp
            if attempt < 3:
                wait = 2 ** attempt
                logger.warning("youtube.rate_limited", attempt=attempt, wait_seconds=wait)
                await asyncio.sleep(wait)
        return resp

    async def _fetch_public_stats(
        self, client: httpx.AsyncClient, video_id: str
    ) -> dict:
        """Fetch public statistics from YouTube Data API v3."""
        params = {
            "part": "statistics",
            "id": video_id,
            "key": settings.youtube_api_key,
        }
        resp = await self._request_with_retry(
            client, f"{YOUTUBE_DATA_API}/videos", params
        )

        if resp.status_code != 200:
            raise ProviderError(
                self.platform, video_id,
                f"Data API returned {resp.status_code}: {resp.text[:200]}",
            )

        items = resp.json().get("items", [])
        if not items:
            return {}

        stats = items[0].get("statistics", {})
        return {
            "video_views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
        }

    async def _fetch_analytics(
        self, client: httpx.AsyncClient, video_id: str, access_token: str
    ) -> dict:
        """Fetch watch time from YouTube Analytics API (requires OAuth)."""
        params = {
            "ids": "channel==MINE",
            "metrics": "estimatedMinutesWatched,views",
            "filters": f"video=={video_id}",
            "startDate": "2000-01-01",
            "endDate": "2099-12-31",
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        resp = await self._request_with_retry(
            client, f"{YOUTUBE_ANALYTICS_API}/reports", params, headers
        )

        if resp.status_code != 200:
            logger.warning(
                "youtube.analytics_api_failed",
                service="collector",
                platform="youtube",
                video_id=video_id,
                status=resp.status_code,
            )
            return {}

        rows = resp.json().get("rows", [])
        if not rows:
            return {}

        # rows[0] = [estimatedMinutesWatched, views]
        minutes_watched = rows[0][0] if len(rows[0]) > 0 else 0
        return {
            "video_watch_time_ms": int(float(minutes_watched) * 60 * 1000),
        }

    async def fetch_metrics(self, post: Post) -> Optional[dict]:
        video_id = post.platform_post_id
        if not video_id:
            return None

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                result: dict = {}

                # Public stats (always available with API key)
                if settings.youtube_api_key:
                    result.update(await self._fetch_public_stats(client, video_id))

                # Analytics (watch time) if OAuth is configured
                access_token = await self._get_oauth_token(client)
                if access_token:
                    analytics = await self._fetch_analytics(client, video_id, access_token)
                    result.update(analytics)

                result["raw"] = {"video_id": video_id, "source": "youtube_data_api"}
                return result if result else None

            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(self.platform, video_id, str(exc)) from exc
