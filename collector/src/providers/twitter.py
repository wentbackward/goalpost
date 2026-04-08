import asyncio
import hashlib
import hmac
import time
import urllib.parse
from base64 import b64encode
from typing import Optional
from uuid import uuid4

import httpx
import structlog

from ..config import settings
from ..models import Post
from .base import BaseProvider, ProviderError

logger = structlog.get_logger()

TWITTER_API_BASE = "https://api.twitter.com"


class TwitterProvider(BaseProvider):
    platform = "twitter"

    async def is_configured(self) -> bool:
        return bool(settings.twitter_bearer_token)

    def _has_user_context(self) -> bool:
        return all([
            settings.twitter_api_key,
            settings.twitter_api_secret,
            settings.twitter_access_token,
            settings.twitter_access_token_secret,
        ])

    def _build_oauth1_header(self, method: str, url: str) -> str:
        """Build OAuth 1.0a Authorization header for user-context requests."""
        oauth_params = {
            "oauth_consumer_key": settings.twitter_api_key,
            "oauth_nonce": uuid4().hex,
            "oauth_signature_method": "HMAC-SHA1",
            "oauth_timestamp": str(int(time.time())),
            "oauth_token": settings.twitter_access_token,
            "oauth_version": "1.0",
        }
        parsed = urllib.parse.urlparse(url)
        query_params = dict(urllib.parse.parse_qsl(parsed.query))
        all_params = {**oauth_params, **query_params}
        sorted_params = "&".join(
            f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
            for k, v in sorted(all_params.items())
        )
        base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        base_string = f"{method.upper()}&{urllib.parse.quote(base_url, safe='')}&{urllib.parse.quote(sorted_params, safe='')}"
        signing_key = f"{urllib.parse.quote(settings.twitter_api_secret, safe='')}&{urllib.parse.quote(settings.twitter_access_token_secret, safe='')}"
        signature = b64encode(
            hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
        ).decode()
        oauth_params["oauth_signature"] = signature
        header_parts = ", ".join(
            f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
            for k, v in sorted(oauth_params.items())
        )
        return f"OAuth {header_parts}"

    async def _request_with_retry(self, client: httpx.AsyncClient, url: str, headers: dict) -> httpx.Response:
        """Make request with exponential backoff on 429."""
        for attempt in range(4):
            resp = await client.get(url, headers=headers)
            if resp.status_code != 429:
                return resp
            if attempt < 3:
                wait = 2 ** attempt
                logger.warning("twitter.rate_limited", attempt=attempt, wait_seconds=wait)
                await asyncio.sleep(wait)
        return resp

    async def fetch_metrics(self, post: Post) -> Optional[dict]:
        tweet_id = post.platform_post_id
        if not tweet_id:
            return None

        # Determine fields and auth based on available credentials
        if self._has_user_context():
            fields = "public_metrics,non_public_metrics,organic_metrics"
        else:
            fields = "public_metrics"

        url = f"{TWITTER_API_BASE}/2/tweets/{tweet_id}?tweet.fields={fields}"

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                if self._has_user_context():
                    auth_header = self._build_oauth1_header("GET", url)
                    headers = {"Authorization": auth_header}
                else:
                    headers = {"Authorization": f"Bearer {settings.twitter_bearer_token}"}

                resp = await self._request_with_retry(client, url, headers)

                if resp.status_code != 200:
                    raise ProviderError(
                        self.platform,
                        tweet_id,
                        f"API returned {resp.status_code}: {resp.text[:200]}"
                    )

                data = resp.json().get("data", {})
                pub = data.get("public_metrics", {})
                non_pub = data.get("non_public_metrics", {})
                organic = data.get("organic_metrics", {})

                impressions = (
                    pub.get("impression_count")
                    or non_pub.get("impression_count")
                    or organic.get("impression_count")
                )

                return {
                    "impressions": impressions,
                    "likes": pub.get("like_count"),
                    "comments": pub.get("reply_count"),
                    "shares": (pub.get("retweet_count", 0) or 0) + (pub.get("quote_count", 0) or 0),
                    "clicks": non_pub.get("url_link_clicks"),
                    "raw": data,
                }

            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(self.platform, tweet_id, str(exc)) from exc

        # Rate limit: 1 req/sec between posts
        await asyncio.sleep(1)
