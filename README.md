# Goalpost — Social Media Analytics Platform

A self-hosted Docker Compose recipe that pairs [Postiz](https://postiz.com) for multi-platform social scheduling with a custom **Analytics Collector** service. Post once, publish everywhere, track engagement across all channels. Optionally, a bundled [Metabase](https://www.metabase.com/) instance gives you point-and-click dashboards — the hard part isn't the visualization, it's wrangling data out of five different platform APIs.

You don't need to be a technical guru to get this running, but you *will* need your favourite AI coding agent riding shotgun. The real challenge is navigating each social platform's labyrinthine developer portal and OAuth setup — let the agent handle that for you.

## Features

- **Multi-platform posting** via Postiz — compose once, publish to X/Twitter, LinkedIn, Instagram, Facebook, YouTube, and more
- **Analytics collector** — pulls engagement metrics (impressions, reach, likes, comments, shares, saves, clicks, video views) from each platform's official API
- **Append-only metric snapshots** — track how each post's performance grows over time, not just current numbers
- **Hashtag analytics** — automatic parsing and aggregation to identify which hashtags drive the most engagement
- **Metabase dashboards** — point-and-click analytics dashboard out of the box
- **REST API** — trigger syncs, register posts, query analytics programmatically
- **Provider pattern** — easy to add new social platforms by implementing a simple interface
- **HTTPS ready** — nginx reverse proxy with TLS cert support (Tailscale, Let's Encrypt, etc.)

## How This Recipe Is Intended To Be Used

This repository is designed to be set up with the help of an AI coding assistant. The platform integrates five social media APIs, each with their own OAuth flows, developer portal quirks, and credential requirements. An AI assistant can walk you through each step interactively.

**To get started:**

1. Clone this repository
2. Open it in [Claude Code](https://claude.ai/code), [Cursor](https://cursor.sh), or your preferred AI coding assistant
3. Give it this bootstrap prompt:

```
I've cloned the Goalpost social media analytics platform. Read CLAUDE.md and
the README to understand the project. Then help me:

1. Set up .env with secure credentials
2. Start the Docker Compose stack
3. Connect my social media accounts to Postiz one at a time
4. Configure the analytics collector with API credentials for each platform
5. Register my existing posts and run the first sync

Walk me through each platform's developer portal setup interactively —
I'll paste credentials as we go. Start with the Docker setup.
```

The assistant will read the documentation, understand the architecture, and guide you through the platform-specific OAuth flows step by step.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Postiz     │     │  Collector   │     │  Metabase    │
│  (port 3060) │     │  (port 8060) │     │  (port 3070) │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                     │
       └────────┬───────────┴─────────────────────┘
                │
         ┌──────┴──────┐     ┌───────┐
         │  PostgreSQL │     │ Redis │
         │   (5432)    │     │(6379) │
         └─────────────┘     └───────┘
                │
         ┌──────┴──────┐
         │  Temporal   │  (workflow engine for Postiz)
         │  + ES + PG  │
         └─────────────┘
```

**Services:** PostgreSQL, Redis, Postiz, Collector (FastAPI), Metabase, nginx (TLS), Temporal stack (4 containers)

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Platform developer accounts for each provider you want to track (see [Platform Credentials](#platform-credentials))
- TLS certificates if you need HTTPS for OAuth callbacks (see [HTTPS Setup](#https-setup))

## Quick Start

```bash
git clone https://github.com/wentbackward/goalpost.git
cd goalpost
cp .env.example .env
```

Edit `.env` — at minimum set:
- `POSTGRES_PASSWORD` — database password (update in `DATABASE_URL` and `COLLECTOR_DATABASE_URL` too)
- `JWT_SECRET` — random string for Postiz authentication
- `COLLECTOR_API_KEY` — bearer token for the collector REST API

Then start everything:

```bash
docker compose up -d
```

The first start will:
1. Pull all images (Postiz, Temporal, Metabase, etc.)
2. Initialize PostgreSQL with the `uuid-ossp` extension and `analytics` schema
3. Run Alembic migrations to create collector tables
4. Start all services

## Default Ports

| Service | Port | Protocol | Notes |
|---|---|---|---|
| Postiz | 3060 | HTTPS (via nginx) | Social media scheduling UI |
| Metabase | 3070 | HTTPS (via nginx) | Analytics dashboards |
| Collector API | 8060 | HTTP | Analytics REST API |
| Collector API | 8443 | HTTPS (via nginx) | Analytics REST API (TLS) |
| Temporal UI | 8080 | HTTP | Workflow monitoring (internal) |

### Changing Ports

Ports are configured in `docker-compose.yml` and `nginx/default.conf`:

- **Postiz:** Change `3060:3060` in docker-compose.yml and `listen 3060` in nginx/default.conf. Update `MAIN_URL` and `NEXT_PUBLIC_BACKEND_URL` in `.env`.
- **Metabase:** Change `3070:3070` in docker-compose.yml and `listen 3070` in nginx/default.conf.
- **Collector:** Change `8060:8000` in docker-compose.yml for direct HTTP. Change `8443:8443` and `listen 8443` in nginx/default.conf for HTTPS.

## HTTPS Setup

HTTPS is required by Meta (Facebook/Instagram) and recommended for all OAuth callback URLs. The included nginx proxy terminates TLS.

### Option 1: Tailscale (recommended for self-hosted)

If your machine is on a [Tailscale](https://tailscale.com) network:

```bash
# Get your machine's Tailscale FQDN
tailscale status

# Generate TLS certificates
sudo tailscale cert \
  --cert-file certs/server.crt \
  --key-file certs/server.key \
  your-machine.your-tailnet.ts.net
```

Update `nginx/default.conf` — replace `your-hostname.example.com` with your Tailscale FQDN.

Update `.env`:
```bash
MAIN_URL=https://your-machine.your-tailnet.ts.net:3060
NEXT_PUBLIC_BACKEND_URL=https://your-machine.your-tailnet.ts.net:3060/api
```

### Option 2: Let's Encrypt / Custom Certificates

Place your certificate and key in the `certs/` directory as `server.crt` and `server.key`. Update the `server_name` in `nginx/default.conf` to match your domain.

### Option 3: No HTTPS (development only)

Remove the nginx service from `docker-compose.yml` and expose Postiz directly:
```yaml
postiz:
  ports:
    - "3060:5000"
```

Note: Meta OAuth (Facebook/Instagram) will not work without HTTPS.

## Postiz Setup

1. Open `https://your-hostname:3060` and create your account
2. Go to **Add Channel** to connect your social media accounts
3. For each platform, you'll need to register OAuth callback URLs in the platform's developer portal:
   - X/Twitter: `https://your-hostname:3060/integrations/social/x`
   - Instagram: `https://your-hostname:3060/integrations/social/instagram`
   - Facebook: `https://your-hostname:3060/integrations/social/facebook`
   - YouTube: `https://your-hostname:3060/integrations/social/youtube`
4. Copy the Postiz API key from Settings → set `POSTIZ_API_KEY` in `.env`

See the [Postiz documentation](https://docs.postiz.com) for full setup details.

## Platform Credentials

Each provider is optional — the collector skips any provider without credentials.

### X / Twitter

Requires a [Twitter Developer App](https://developer.twitter.com/) (Free tier for basic, Basic tier for full metrics).

| Variable | Required | Notes |
|---|---|---|
| `TWITTER_BEARER_TOKEN` | Yes | App-level bearer token for public metrics |
| `TWITTER_API_KEY` | No | Consumer Key — for user-context (non-public metrics) |
| `TWITTER_API_SECRET` | No | Consumer Secret |
| `TWITTER_ACCESS_TOKEN` | No | OAuth 1.0a access token |
| `TWITTER_ACCESS_TOKEN_SECRET` | No | OAuth 1.0a access token secret |

For Postiz publishing, also set `X_API_KEY` and `X_API_SECRET` (same as Consumer Key/Secret).

**Twitter Developer Portal setup:**
1. Create a project and app
2. Under "User authentication settings", set up OAuth 1.0a with Read and Write permissions
3. Add callback URL: `https://your-hostname:3060/integrations/social/x`
4. Generate Bearer Token, Access Token, and Access Token Secret under "Keys and Tokens"

### LinkedIn

Requires a [LinkedIn Developer App](https://www.linkedin.com/developers/) with Community Management API access (for analytics) or Share on LinkedIn (for posting only).

| Variable | Required | Notes |
|---|---|---|
| `LINKEDIN_ACCESS_TOKEN` | Yes | 60-day token; refresh manually |

Use `scripts/linkedin_oauth.py` to generate the access token:
```bash
LINKEDIN_CLIENT_ID=your_id LINKEDIN_CLIENT_SECRET=your_secret python3 scripts/linkedin_oauth.py
```

### Instagram

Requires a Business or Creator account linked to a Facebook Page. Uses the [Instagram Business API](https://developers.facebook.com/docs/instagram-api/).

| Variable | Required | Notes |
|---|---|---|
| `INSTAGRAM_ACCESS_TOKEN` | Yes | Token from Instagram Business API setup |
| `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Yes | Instagram Business Account ID |

The Instagram token is generated in the Meta Developer Portal under your app's Instagram Business API configuration.

### Facebook

Uses the [Meta Graph API](https://developers.facebook.com/docs/graph-api/) for Page insights. Only tracks **Page posts** (not personal profile posts — Meta API limitation).

| Variable | Required | Notes |
|---|---|---|
| `FACEBOOK_ACCESS_TOKEN` | Yes | Long-lived Page access token |
| `FACEBOOK_PAGE_ID` | Yes | Facebook Page ID |

Use `scripts/meta_oauth.py` to generate the Page access token:
```bash
META_APP_ID=your_id META_APP_SECRET=your_secret python3 scripts/meta_oauth.py
```

### YouTube

Requires a [Google Cloud project](https://console.cloud.google.com/) with YouTube Data API v3 enabled.

| Variable | Required | Notes |
|---|---|---|
| `YOUTUBE_API_KEY` | Yes* | For public video statistics (views, likes, comments) |
| `YOUTUBE_OAUTH_CLIENT_ID` | No | For private analytics (watch time) |
| `YOUTUBE_OAUTH_CLIENT_SECRET` | No | For private analytics |
| `YOUTUBE_REFRESH_TOKEN` | No | For private analytics |
| `YOUTUBE_CHANNEL_ID` | No | Channel filter |

*Either `YOUTUBE_API_KEY` or OAuth credentials are required.

## API Usage

All endpoints (except `/health`) require `Authorization: Bearer <COLLECTOR_API_KEY>`.

### Health Check

```bash
curl http://localhost:8060/health
```

### Trigger a Full Sync

```bash
curl -X POST http://localhost:8060/sync \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Trigger a Single-Platform Sync

```bash
curl -X POST http://localhost:8060/sync/twitter \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Check Sync Status

```bash
curl http://localhost:8060/sync/<sync_id> \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Register a Post Manually

For posts published outside Postiz or before setup:

```bash
curl -X POST http://localhost:8060/posts/register \
  -H "Authorization: Bearer $COLLECTOR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "twitter",
    "platform_post_id": "1234567890",
    "content_text": "My tweet #hashtag",
    "media_type": "text",
    "published_at": "2026-04-07T09:00:00Z"
  }'
```

### List Posts

```bash
curl "http://localhost:8060/posts?platform=twitter&limit=10" \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Get Post Metric History

```bash
curl http://localhost:8060/posts/<post_id>/metrics \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Analytics Summary

```bash
curl "http://localhost:8060/analytics/summary?start_date=2026-04-01T00:00:00Z&end_date=2026-04-07T23:59:59Z" \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

### Hashtag Analytics

```bash
curl "http://localhost:8060/analytics/hashtags?limit=25" \
  -H "Authorization: Bearer $COLLECTOR_API_KEY"
```

## Metabase Dashboards

Metabase is available at `https://your-hostname:3070`. On first access, create an admin account and connect to the database:

- **Database type:** PostgreSQL
- **Host:** `postgres`
- **Port:** 5432
- **Database:** `social_analytics`
- **Username/Password:** from your `.env`

The `analytics` schema contains all collector tables. Start with a "New Question" to explore your data.

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
        # Return dict with keys: impressions, reach, likes, comments,
        #   shares, saves, clicks, video_views, video_watch_time_ms, raw
        # Return None if unavailable
        # Raise ProviderError on hard failures
        ...
```

3. Add your env vars to `config.py` and `.env.example`
4. Register in `collector/src/providers/__init__.py`

## Database Access

Connect any tool to the shared PostgreSQL instance:

```
postgresql://<user>:<password>@localhost:5432/social_analytics
```

Collector tables in the `analytics` schema:
- `analytics.posts` — tracked posts across all platforms
- `analytics.post_metrics` — append-only metric snapshots (one row per post per sync)
- `analytics.post_hashtags` — parsed hashtags per post
- `analytics.sync_log` — sync run history

Postiz uses the `public` schema in the same database.

## Postiz Bridge

The collector discovers posts published via Postiz automatically. Controlled by `POSTIZ_BRIDGE_MODE`:

- **`db`** (default) — queries Postiz's `public.posts` table directly
- **`api`** — uses `GET /public/v1/posts` with `POSTIZ_API_KEY`

## License

MIT License — Copyright (c) 2026 Paul Gresham Advisory LLC

See [LICENSE](LICENSE) for full text and third-party component licenses.
