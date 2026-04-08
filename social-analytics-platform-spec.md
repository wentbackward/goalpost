# Social Media Analytics Platform — Claude Code Spec

**Project:** `social-analytics`  
**Author:** Paul Gresham Advisory LLC  
**Status:** Draft for implementation  

---

## Overview

Build a self-hosted Docker Compose platform that:

1. Runs **Postiz** for multi-platform social media scheduling and posting
2. Runs a custom **Analytics Collector** service that pulls post-level engagement data from X/Twitter, LinkedIn, Instagram, Facebook, and YouTube via their official APIs
3. Stores all data in a shared **PostgreSQL** database
4. Exposes a **REST API** to trigger analytics pulls on demand and query aggregated data

No dashboard is included — the database and API are the integration surface. A separate frontend will be built later.

---

## Repository Structure

```
social-analytics/
├── docker-compose.yml
├── .env.example
├── README.md
├── collector/                  # Custom analytics collector service
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/
│   │   ├── main.py             # FastAPI app entrypoint
│   │   ├── config.py           # Settings via pydantic-settings
│   │   ├── database.py         # SQLAlchemy async engine + session
│   │   ├── models.py           # ORM models
│   │   ├── schemas.py          # Pydantic request/response schemas
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── sync.py         # POST /sync endpoints
│   │   │   └── analytics.py    # GET /analytics endpoints
│   │   └── providers/
│   │       ├── __init__.py
│   │       ├── base.py         # Abstract base provider
│   │       ├── twitter.py      # X / Twitter v2 API
│   │       ├── linkedin.py     # LinkedIn API
│   │       ├── instagram.py    # Meta Graph API (Instagram)
│   │       ├── facebook.py     # Meta Graph API (Facebook Pages)
│   │       └── youtube.py      # YouTube Data API v3
│   └── alembic/                # Database migrations
│       ├── env.py
│       └── versions/
└── init-db/
    └── 01-extensions.sql       # pg extensions (uuid-ossp, etc.)
```

---

## Docker Compose Services

### `docker-compose.yml`

Define the following services. Use named volumes for persistence. All services share a `social-analytics` bridge network.

| Service | Image / Build | Ports | Notes |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5432 (internal only) | Shared DB for Postiz + collector |
| `redis` | `redis:7-alpine` | 6379 (internal only) | Required by Postiz |
| `postiz` | `ghcr.io/gitroomhq/postiz-app:latest` | 3000→3000 | Social scheduling UI + API |
| `collector` | Build from `./collector` | 8000→8000 | Analytics collector (FastAPI) |

**Startup order:** postgres → redis → postiz, collector (both depend on postgres healthy)

**Postgres healthcheck:** `pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}`

**Shared database:** Postiz and the collector share the same Postgres instance but use separate schemas:
- Postiz uses its default schema (`public`)
- Collector uses schema `analytics`

The collector should create the `analytics` schema and its tables via Alembic migrations on startup.

---

## Environment Variables

### `.env.example`

Provide a fully-commented `.env.example`. Required variables:

```bash
# --- Postgres ---
POSTGRES_USER=social
POSTGRES_PASSWORD=changeme
POSTGRES_DB=social_analytics

# --- Postiz (pass-through — see Postiz docs for full list) ---
DATABASE_URL=postgresql://social:changeme@postgres:5432/social_analytics
REDIS_URL=redis://redis:6379
JWT_SECRET=changeme_jwt_secret
POSTIZ_API_KEY=                    # Set after first run; used by collector
NEXT_PUBLIC_BACKEND_URL=http://localhost:3000

# --- Collector ---
COLLECTOR_API_KEY=changeme_collector_key   # Bearer token for collector API

# --- Platform credentials (all optional; collector skips disabled providers) ---

# X / Twitter — requires Twitter Developer App (Basic tier minimum for read)
TWITTER_BEARER_TOKEN=
TWITTER_API_KEY=
TWITTER_API_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_TOKEN_SECRET=

# LinkedIn — requires LinkedIn Developer App with r_organization_social scope
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_ACCESS_TOKEN=             # Long-lived token (60 days); refresh manually for now

# Instagram — Meta Graph API; requires Business/Creator account linked to FB Page
INSTAGRAM_ACCESS_TOKEN=            # Long-lived page token
INSTAGRAM_BUSINESS_ACCOUNT_ID=

# Facebook — Meta Graph API; Page access token
FACEBOOK_ACCESS_TOKEN=
FACEBOOK_PAGE_ID=

# YouTube — Google Cloud project with YouTube Data API v3 enabled
YOUTUBE_API_KEY=                   # For public channel data
YOUTUBE_OAUTH_CLIENT_ID=           # For private video analytics
YOUTUBE_OAUTH_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
YOUTUBE_CHANNEL_ID=
```

---

## Collector Service — Detail

### Technology Stack

- **Python 3.12**
- **FastAPI** — async REST API
- **SQLAlchemy 2.x** (async) + **asyncpg** driver
- **Alembic** — migrations
- **pydantic-settings** — config from env
- **httpx** — async HTTP client for platform APIs
- **google-api-python-client** — YouTube Data API v3

### Database Models (`analytics` schema)

#### `analytics.posts`

Tracks every post that Postiz has published, sourced by polling the Postiz internal DB or Postiz public API.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `postiz_post_id` | VARCHAR | ID from Postiz `posts` table or API |
| `platform` | VARCHAR | `twitter`, `linkedin`, `instagram`, `facebook`, `youtube` |
| `platform_post_id` | VARCHAR | Native post ID returned by the platform |
| `content_text` | TEXT | Caption / post text |
| `media_type` | VARCHAR | `image`, `gif`, `video`, `text` |
| `published_at` | TIMESTAMPTZ | When the post went live |
| `created_at` | TIMESTAMPTZ | Row created |
| `updated_at` | TIMESTAMPTZ | Row updated |

Unique constraint: `(platform, platform_post_id)`

#### `analytics.post_metrics`

One row per post per sync. Append-only — captures a snapshot at each pull.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `post_id` | UUID FK → `analytics.posts.id` | |
| `synced_at` | TIMESTAMPTZ | When this snapshot was taken |
| `impressions` | BIGINT | |
| `reach` | BIGINT | |
| `likes` | BIGINT | |
| `comments` | BIGINT | |
| `shares` | BIGINT | |
| `saves` | BIGINT | Instagram saves / LinkedIn bookmarks |
| `clicks` | BIGINT | Link clicks where available |
| `video_views` | BIGINT | NULL for non-video posts |
| `video_watch_time_ms` | BIGINT | YouTube / Facebook only |
| `raw` | JSONB | Full raw API response for future-proofing |

#### `analytics.sync_log`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `triggered_at` | TIMESTAMPTZ | |
| `platform` | VARCHAR | NULL = all platforms |
| `posts_synced` | INT | |
| `posts_failed` | INT | |
| `error_summary` | TEXT | |
| `duration_ms` | INT | |

---

### Provider Implementations

Each provider lives in `collector/src/providers/<platform>.py` and extends `BaseProvider`:

```python
# base.py (implement this interface exactly)
from abc import ABC, abstractmethod
from typing import Optional
from ..models import Post

class BaseProvider(ABC):
    platform: str

    @abstractmethod
    async def is_configured(self) -> bool:
        """Return True if all required env vars are present."""
        ...

    @abstractmethod
    async def fetch_metrics(self, post: Post) -> Optional[dict]:
        """
        Fetch current engagement metrics for a single post.
        Return a dict matching post_metrics columns, or None if unavailable.
        Raise ProviderError on hard failures.
        """
        ...
```

#### Provider-specific implementation notes

**Twitter (`twitter.py`)**
- Use Twitter API v2 via `httpx` (not Tweepy, to stay async)
- Endpoint: `GET /2/tweets/:id` with `tweet.fields=public_metrics,non_public_metrics,organic_metrics`
- `public_metrics`: retweet_count, reply_count, like_count, quote_count, impression_count
- `non_public_metrics` and `organic_metrics` require OAuth 1.0a user context (not bearer token) — only attempt if user-level tokens are configured, otherwise fall back to public metrics
- Map: impressions→impressions, like_count→likes, reply_count→comments, retweet_count+quote_count→shares
- Rate limit: 1 request per second; add `asyncio.sleep(1)` between posts

**LinkedIn (`linkedin.py`)**
- Use LinkedIn Marketing API
- Endpoint: `GET /v2/organizationalEntityShareStatistics` with `q=organizationalEntity`
- Requires `r_organization_social` OAuth scope
- Metrics: impressions, clicks, likes, comments, shares
- Token expires every 60 days — log a clear warning when expiry is within 7 days (check `x-li-format` header or token introspection)

**Instagram (`instagram.py`)**
- Use Meta Graph API v18+
- Endpoint: `GET /{media-id}/insights` with `metric=impressions,reach,likes,comments,shares,saved,video_views`
- Requires Instagram Business or Creator account
- For Reels, use `metric=plays,reach,likes,comments,shares,saved` (different metric names)
- Detect media type from `post.media_type` and adjust metric list accordingly

**Facebook (`facebook.py`)**
- Use Meta Graph API v18+
- Endpoint: `GET /{post-id}/insights` with `metric=post_impressions,post_reach,post_reactions_like_total,post_comments,post_shares,post_clicks,post_video_views,post_video_avg_time_watched`
- Page access token required (not user token)

**YouTube (`youtube.py`)**
- Use `google-api-python-client` with `googleapiclient.discovery.build('youtubeAnalytics', 'v2')`
- For public stats: `youtube.videos().list(part='statistics', id=video_id)`
- For full analytics (watch time etc): YouTube Analytics API — requires OAuth; use refresh token flow
- Map: viewCount→video_views, likeCount→likes, commentCount→comments
- Watch time from Analytics API: `reports().query(ids='channel==MINE', metrics='estimatedMinutesWatched,views', filters=f'video=={video_id}')`

---

### REST API (`FastAPI`)

All endpoints require `Authorization: Bearer <COLLECTOR_API_KEY>` header.

#### `POST /sync`

Trigger a full analytics sync across all configured platforms for all known posts.

**Request body:** none  
**Response:**
```json
{
  "sync_id": "uuid",
  "platforms_triggered": ["twitter", "linkedin", "instagram", "facebook", "youtube"],
  "platforms_skipped": [],
  "status": "started"
}
```
Sync runs as a background task. Poll `/sync/{sync_id}` for status.

#### `POST /sync/{platform}`

Sync a single platform only. Same response shape, `platforms_triggered` has one entry.

#### `GET /sync/{sync_id}`

**Response:**
```json
{
  "sync_id": "uuid",
  "status": "running | completed | failed",
  "triggered_at": "2026-04-07T09:00:00Z",
  "completed_at": "2026-04-07T09:01:23Z",
  "posts_synced": 42,
  "posts_failed": 1,
  "error_summary": null,
  "duration_ms": 83000
}
```

#### `POST /posts/register`

Manually register a post for tracking (for posts published outside Postiz or before setup).

**Request body:**
```json
{
  "platform": "twitter",
  "platform_post_id": "1234567890",
  "content_text": "Optional caption",
  "media_type": "image",
  "published_at": "2026-04-07T09:00:00Z"
}
```

#### `GET /posts`

Query registered posts with optional filters.

**Query params:** `platform`, `media_type`, `published_after`, `published_before`, `limit` (default 50), `offset`

**Response:** paginated list of posts with their most recent metrics snapshot included.

#### `GET /posts/{post_id}/metrics`

Full metric history for a single post (all snapshots).

**Response:**
```json
{
  "post": { ... },
  "metrics": [
    {
      "synced_at": "...",
      "impressions": 1200,
      "likes": 45,
      "comments": 8,
      "shares": 12,
      "video_views": null,
      ...
    }
  ]
}
```

#### `GET /analytics/summary`

Aggregated stats across all platforms for a time window.

**Query params:** `start_date`, `end_date`, `platform` (optional), `media_type` (optional)

**Response:**
```json
{
  "period": { "start": "...", "end": "..." },
  "totals": {
    "posts": 32,
    "impressions": 48200,
    "likes": 1240,
    "comments": 89,
    "shares": 210,
    "video_views": 8900
  },
  "by_platform": {
    "twitter": { "posts": 10, "impressions": 12000, ... },
    "linkedin": { ... },
    ...
  },
  "by_media_type": {
    "image": { ... },
    "video": { ... }
  },
  "top_posts": [
    {
      "post_id": "uuid",
      "platform": "linkedin",
      "published_at": "...",
      "impressions": 9800,
      "engagement_rate": 0.042
    }
  ]
}
```

`engagement_rate` = (likes + comments + shares) / impressions

#### `GET /health`

No auth required. Returns `{"status": "ok", "db": "ok", "providers": {"twitter": "configured", "linkedin": "configured", "youtube": "missing_token"}}`.

---

## Postiz Integration

The collector needs to know which posts exist and their platform post IDs. There are two sources:

**Option A — Direct DB query (preferred for self-hosted):**  
The collector connects to the shared Postgres instance and queries Postiz's `posts` table to discover published posts and their native platform IDs. Postiz stores the platform post ID in its `posts` table (column name to verify by inspecting the schema on startup). Write a `postiz_bridge.py` module that:
1. On startup, queries Postiz tables to discover schema
2. Exposes `async def get_published_posts(since: datetime) -> list[PostizPost]`
3. Syncs new Postiz posts into `analytics.posts` before each analytics pull

**Option B — Postiz public API (fallback):**  
If direct DB access is unavailable, use `GET /public/v1/posts` with the `POSTIZ_API_KEY`. Implement this as a fallback in `postiz_bridge.py`.

Prefer Option A, but implement both with a config flag `POSTIZ_BRIDGE_MODE=db|api`.

---

## Startup Behaviour

The collector container should on startup:

1. Wait for Postgres to be ready (retry with backoff, max 30s)
2. Run `alembic upgrade head` to apply migrations
3. Create `analytics` schema if not exists
4. Discover Postiz DB schema (log findings)
5. Start FastAPI on `0.0.0.0:8000`

---

## Error Handling & Resilience

- Per-post failures during a sync must not abort the entire sync — log the error, increment `posts_failed`, continue
- Platform API rate limit responses (429) must be handled: back off and retry up to 3 times with exponential backoff before marking the post as failed for that sync
- Each provider should catch and wrap all exceptions as `ProviderError` with the platform name and post ID included
- All errors must be logged as structured JSON (use Python `structlog` library)

---

## Logging

Use `structlog` configured for JSON output. Every log entry should include:
- `timestamp`
- `level`
- `service: "collector"`
- `platform` (where applicable)
- `post_id` (where applicable)
- `sync_id` (where applicable)

---

## README Requirements

The README must document:

1. **Prerequisites** — Docker, Docker Compose v2, platform developer account requirements per provider
2. **First run** — `cp .env.example .env`, edit values, `docker compose up -d`
3. **Postiz setup** — link to Postiz docs for connecting social accounts; note that `POSTIZ_API_KEY` is found in Postiz Settings after first run
4. **Platform credential setup** — per-platform instructions for obtaining tokens (concise, link to official docs)
5. **API usage** — curl examples for all endpoints
6. **Extending** — how to add a new platform provider (implement `BaseProvider`, register in provider registry)
7. **Database access** — connection string for plugging in Metabase, Grafana, or a custom frontend

---

## Acceptance Criteria

Claude Code should verify the following before considering the implementation complete:

- [ ] `docker compose up -d` starts all services without errors
- [ ] `GET /health` returns 200 with provider status
- [ ] `POST /sync` returns a sync ID and completes without crashing (even if all providers return no data due to missing tokens)
- [ ] `GET /analytics/summary` returns a valid response shape for an empty database
- [ ] Alembic migrations apply cleanly on a fresh database
- [ ] All providers fail gracefully when credentials are missing (skip, log warning, do not crash)
- [ ] `.env.example` contains every required variable with comments
- [ ] Structured JSON logs appear in `docker compose logs collector`

---

## Out of Scope for This Build

- Authentication/authorisation beyond the single `COLLECTOR_API_KEY` bearer token
- Token refresh automation (LinkedIn, YouTube OAuth) — log warnings, document manual refresh process
- A frontend dashboard
- Historical backfill beyond what platform APIs return for existing post IDs
- Webhook ingestion from platforms

---

*Spec version: 1.0 — April 2026*  
*© 2026 Paul Gresham Advisory LLC*