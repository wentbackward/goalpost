import asyncio
from typing import Optional

import httpx
import structlog

from ..config import settings
from ..models import Post
from .base import BaseProvider, ProviderError

logger = structlog.get_logger()

LINKEDIN_API_BASE = "https://api.linkedin.com"


class LinkedInProvider(BaseProvider):
    platform = "linkedin"

    async def is_configured(self) -> bool:
        return bool(settings.linkedin_access_token)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {settings.linkedin_access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": "202304",
        }

    async def _check_token_expiry(self, client: httpx.AsyncClient) -> None:
        """Log a warning if the LinkedIn token is close to expiring."""
        try:
            resp = await client.get(
                f"{LINKEDIN_API_BASE}/v2/me",
                headers=self._headers(),
            )
            # LinkedIn doesn't expose expiry in a standard header, but a 401
            # means the token is already expired
            if resp.status_code == 401:
                logger.warning(
                    "linkedin.token_expired",
                    service="collector",
                    platform="linkedin",
                    message="LinkedIn access token has expired. Please refresh it manually.",
                )
        except Exception:
            pass

    async def _request_with_retry(
        self, client: httpx.AsyncClient, url: str, params: dict | None = None
    ) -> httpx.Response:
        for attempt in range(4):
            resp = await client.get(url, headers=self._headers(), params=params)
            if resp.status_code != 429:
                return resp
            if attempt < 3:
                wait = 2 ** attempt
                logger.warning("linkedin.rate_limited", attempt=attempt, wait_seconds=wait)
                await asyncio.sleep(wait)
        return resp

    async def fetch_metrics(self, post: Post) -> Optional[dict]:
        post_urn = post.platform_post_id
        if not post_urn:
            return None

        # Ensure URN format — if just an ID, wrap it
        if not post_urn.startswith("urn:"):
            post_urn = f"urn:li:share:{post_urn}"

        async with httpx.AsyncClient(timeout=30) as client:
            await self._check_token_expiry(client)

            try:
                # Get social metadata (likes, comments, shares) via socialMetadata
                resp = await self._request_with_retry(
                    client,
                    f"{LINKEDIN_API_BASE}/v2/socialMetadata/{post_urn}",
                )

                if resp.status_code == 401:
                    raise ProviderError(
                        self.platform, post_urn,
                        "Access token expired. Refresh manually (60-day token).",
                    )

                if resp.status_code != 200:
                    raise ProviderError(
                        self.platform, post_urn,
                        f"API returned {resp.status_code}: {resp.text[:200]}",
                    )

                data = resp.json()

                # Also try organizational share statistics for impressions/clicks
                stats = {}
                stats_resp = await self._request_with_retry(
                    client,
                    f"{LINKEDIN_API_BASE}/v2/organizationalEntityShareStatistics",
                    params={
                        "q": "organizationalEntity",
                        "shares[0]": post_urn,
                    },
                )
                if stats_resp.status_code == 200:
                    elements = stats_resp.json().get("elements", [])
                    if elements:
                        stats = elements[0].get("totalShareStatistics", {})

                return {
                    "impressions": stats.get("impressionCount"),
                    "clicks": stats.get("clickCount"),
                    "likes": data.get("likeCount") or stats.get("likeCount"),
                    "comments": data.get("commentCount") or stats.get("commentCount"),
                    "shares": data.get("shareCount") or stats.get("shareCount"),
                    "reach": stats.get("uniqueImpressionsCount"),
                    "raw": {"socialMetadata": data, "shareStatistics": stats},
                }

            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(self.platform, post_urn, str(exc)) from exc
