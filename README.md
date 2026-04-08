# Social Media Analytics Platform

Self-hosted Docker Compose platform that runs [Postiz](https://postiz.com) for social media scheduling alongside a custom **Analytics Collector** service. The collector pulls post-level engagement data from X/Twitter, LinkedIn, Instagram, Facebook, and YouTube via their official APIs.

No dashboard included — the PostgreSQL database and REST API are the integration surface.

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Platform developer accounts for each provider you want to track (see [Platform Credentials](#platform-credentials))

## Quick Start

```bash
cp .env.example .env
# Edit .env — set at minimum POSTGRES_PASSWORD, JWT_SECRET, COLLECTOR_API_KEY
docker compose up -d
```

The first start will:
1. Initialize PostgreSQL with the `uuid-ossp` extension and `analytics` schema
2. Run Alembic migrations to create collector tables
3. Start Postiz on port **3000** and the Collector API on port **8000**

## Postiz Setup

1. Open `http://localhost:3000` and create your account
2. Connect your social media accounts via Postiz Settings
3. Copy the API key from Postiz Settings → set `POSTIZ_API_KEY` in `.env`
4. Restart: `docker compose restart collector`

See the [Postiz documentation](https://docs.postiz.com) for full setup details.

## Platform Credentials

Each provider is optional — the collector skips any provider without credentials.

### X / Twitter

Requires a [Twitter Developer App](https://developer.twitter.com/) (Basic tier minimum).

| Variable | Required | Notes |
|---|---|---|
| `TWITTER_BEARER_TOKEN` | Yes | App-level bearer token for public metrics |
| `TWITTER_API_KEY` | No | For user-context (non-public metrics) |
| `TWITTER_API_SECRET` | No | For user-context |
| `TWITTER_ACCESS_TOKEN` | No | For user-context |
| `TWITTER_ACCESS_TOKEN_SECRET` | No | For user-context |

### LinkedIn

Requires a [LinkedIn Developer App](https://www.linkedin.com/developers/) with `r_organization_social` scope.

| Variable | Required | Notes |
|---|---|---|
| `LINKEDIN_ACCESS_TOKEN` | Yes | 60-day token; refresh manually |

The collector logs a warning when the token has expired (401 response).

### Instagram

Requires a Business or Creator account linked to a Facebook Page. Uses the [Meta Graph API](https://developers.facebook.com/docs/instagram-api/).

| Variable | Required | Notes |
|---|---|---|
| `INSTAGRAM_ACCESS_TOKEN` | Yes | Long-lived page token |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Yes | Instagram Business Account ID |

### Facebook

Uses the [Meta Graph API](https://developers.facebook.com/docs/graph-api/) for Page insights.

| Variable | Required | Notes |
|---|---|---|
| `FACEBOOK_ACCESS_TOKEN` | Yes | Page access token (not user token) |
| `FACEBOOK_PAGE_ID` | Yes | Facebook Page ID |

### YouTube

Requires a [Google Cloud project](https://console.cloud.google.com/) with YouTube Data API v3 enabled.

| Variable | Required | Notes |
|---|---|---|
| `YOUTUBE_API_KEY` | Yes* | For public video statistics |
| `YOUTUBE_OAUTH_CLIENT_ID` | No | For watch time analytics |
| `YOUTUBE_OAUTH_CLIENT_SECRET` | No | For watch time analytics |
| `YOUTUBE_REFRESH_TOKEN` | No | For watch time analytics |
| `YOUTUBE_CHANNEL_ID` | No | Channel filter |

*Either `YOUTUBE_API_KEY` or OAuth credentials are required.

## API Usage

All endpoints (except `/health`) require `Authorization: Bearer <COLLECTOR_API_KEY>`.

### Health Check

```bash
curl http://localhost:8000/health
```

### Trigger a Full Sync

```bash
curl -X POST http://localhost:8000/sync \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Trigger a Single-Platform Sync

```bash
curl -X POST http://localhost:8000/sync/twitter \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Check Sync Status

```bash
curl http://localhost:8000/sync/<sync_id> \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Register a Post Manually

For posts published outside Postiz or before setup:

```bash
curl -X POST http://localhost:8000/posts/register \
  -H "Authorization: Bearer $COLLECTOR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "twitter",
    "platform_post_id": "1234567890",
    "content_text": "My tweet",
    "media_type": "text",
    "published_at": "2026-04-07T09:00:00Z"
  }'
```

### List Posts

```bash
# All posts
curl "http://localhost:8000/posts" \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"

# Filtered
curl "http://localhost:8000/posts?platform=twitter&media_type=image&limit=10" \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Get Post Metric History

```bash
curl http://localhost:8000/posts/<post_id>/metrics \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Analytics Summary

```bash
curl "http://localhost:8000/analytics/summary?start_date=2026-04-01T00:00:00Z&end_date=2026-04-07T23:59:59Z" \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

## Extending — Adding a New Provider

1. Create `collector/src/providers/myplatform.py`
2. Implement the `BaseProvider` interface:

```python
from .base import BaseProvider, ProviderError
from ..models import Post
from ..config import settings

class MyPlatformProvider(BaseProvider):
    platform = "myplatform"

    async def is_configured(self) -> bool:
        return bool(settings.myplatform_api_key)

    async def fetch_metrics(self, post: Post) -> dict | None:
        # Fetch metrics from the platform API
        # Return dict with keys: impressions, reach, likes, comments,
        #   shares, saves, clicks, video_views, video_watch_time_ms, raw
        # Return None if unavailable
        # Raise ProviderError on hard failures
        ...
```

3. Add your env vars to `config.py` and `.env.example`
4. Register the provider in `collector/src/providers/__init__.py`:

```python
from .myplatform import MyPlatformProvider

PROVIDER_REGISTRY: list[type[BaseProvider]] = [
    ...,
    MyPlatformProvider,
]
```

## Database Access

Connect any analytics tool (Metabase, Grafana, custom frontend) to the shared PostgreSQL instance:

```
postgresql://social:changeme@localhost:5432/social_analytics
```

Collector tables live in the `analytics` schema:
- `analytics.posts` — tracked posts across all platforms
- `analytics.post_metrics` — append-only metric snapshots (one row per post per sync)
- `analytics.sync_log` — sync run history

Postiz uses the `public` schema in the same database.

## Postiz Bridge

The collector discovers posts published via Postiz automatically. Controlled by `POSTIZ_BRIDGE_MODE`:

- **`db`** (default) — queries Postiz's `public.posts` table directly (fastest, no extra config)
- **`api`** — uses `GET /public/v1/posts` with `POSTIZ_API_KEY` (use if direct DB access is restricted)

## Architecture

```
┌─────────────┐     ┌─────────────┐
│   Postiz    │     │  Collector  │
│  (port 3000)│     │ (port 8000) │
└──────┬──────┘     └──────┬──────┘
       │                   │
       └───────┬───────────┘
               │
        ┌──────┴──────┐     ┌───────┐
        │  PostgreSQL │     │ Redis │
        │  (port 5432)│     │(6379) │
        └─────────────┘     └───────┘
```
