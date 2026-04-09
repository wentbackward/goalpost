import asyncio
from typing import Optional
from urllib.parse import quote

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

        encoded_urn = quote(post_urn, safe="")

        async with httpx.AsyncClient(timeout=30) as client:
            await self._check_token_expiry(client)

            try:
                likes = 0
                comments = 0
                shares = 0
                raw = {}

                # Get likes count via socialActions
                likes_resp = await self._request_with_retry(
                    client,
                    f"{LINKEDIN_API_BASE}/v2/socialActions/{encoded_urn}/likes",
                    params={"count": 0},
                )
                if likes_resp.status_code == 200:
                    likes_data = likes_resp.json()
                    likes = likes_data.get("paging", {}).get("total", 0)
                    raw["likes"] = likes_data

                # Get comments count via socialActions
                comments_resp = await self._request_with_retry(
                    client,
                    f"{LINKEDIN_API_BASE}/v2/socialActions/{encoded_urn}/comments",
                    params={"count": 0},
                )
                if comments_resp.status_code == 200:
                    comments_data = comments_resp.json()
                    comments = comments_data.get("paging", {}).get("total", 0)
                    raw["comments"] = comments_data

                # Try organizational share statistics for impressions/clicks
                # (requires Community Management API — may 403)
                impressions = None
                clicks = None
                reach = None
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
                        impressions = stats.get("impressionCount")
                        clicks = stats.get("clickCount")
                        reach = stats.get("uniqueImpressionsCount")
                        shares = stats.get("shareCount", shares)
                        raw["shareStatistics"] = stats

                # Check if we got anything at all
                if likes_resp.status_code == 401 or comments_resp.status_code == 401:
                    raise ProviderError(
                        self.platform, post_urn,
                        "Access token expired. Refresh manually (60-day token).",
                    )

                if likes_resp.status_code not in (200, 403) and comments_resp.status_code not in (200, 403):
                    raise ProviderError(
                        self.platform, post_urn,
                        f"API returned likes={likes_resp.status_code} comments={comments_resp.status_code}",
                    )

                return {
                    "impressions": impressions,
                    "clicks": clicks,
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                    "reach": reach,
                    "raw": raw,
                }

            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(self.platform, post_urn, str(exc)) from exc
