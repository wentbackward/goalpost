# Goalpost — Social Media Analytics Platform

## Project Overview

Self-hosted Docker Compose platform that pairs Postiz (multi-platform social scheduling) with a custom FastAPI analytics collector. Pulls engagement metrics from X/Twitter, LinkedIn, Instagram, Facebook, and YouTube into PostgreSQL with append-only metric snapshots over time.

## Key Documentation

- `social-analytics-platform-spec.md` — Full platform specification (data models, API contracts, provider details)
- `docs/dashboard-design.md` — Frontend dashboard design (Next.js + Tremor + Recharts)
- `README.md` — Setup guide, port reference, API usage, platform credential setup

## Architecture

```
Postiz (scheduling) → Social Platforms ← Collector (analytics)
                                            ↓
                                     PostgreSQL (analytics schema)
                                            ↓
                                     Metabase (dashboards)
```

## Code Layout

- `collector/` — Custom FastAPI analytics service (Python 3.12)
  - `src/main.py` — App entrypoint
  - `src/models.py` — SQLAlchemy ORM models (posts, post_metrics, post_hashtags, sync_log)
  - `src/providers/` — Platform-specific API integrations (base.py defines the interface)
  - `src/routers/` — API endpoints (sync.py, analytics.py)
  - `src/hashtags.py` — Hashtag extraction from post content
  - `src/postiz_bridge.py` — Discovers posts from Postiz DB or API
  - `alembic/` — Database migrations
- `scripts/` — OAuth helper scripts for LinkedIn and Meta token generation
- `nginx/` — HTTPS reverse proxy config (requires TLS certs)
- `dynamicconfig/` — Temporal workflow engine config
- `init-db/` — PostgreSQL initialization (extensions + schema)

## Key Patterns

- **Provider pattern:** Each social platform implements `BaseProvider` (ABC) with `is_configured()` and `fetch_metrics()`. Register new providers in `providers/__init__.py`.
- **Append-only metrics:** `post_metrics` table captures a snapshot per post per sync — never updated, always appended.
- **Hashtag analytics:** Hashtags are parsed from `content_text` during sync and stored in `post_hashtags` for aggregation.
- **Auth:** Single bearer token (`COLLECTOR_API_KEY`) for all collector endpoints. `/health` is unauthenticated.

## Database

PostgreSQL with two schemas:
- `public` — Postiz tables (managed by Postiz/Prisma)
- `analytics` — Collector tables (managed by Alembic)

Key tables: `analytics.posts`, `analytics.post_metrics`, `analytics.post_hashtags`, `analytics.sync_log`

## Running

```bash
cp .env.example .env   # Edit credentials
docker compose up -d   # Start all services
```

## Testing Changes

After modifying collector code:
```bash
docker compose build collector
docker compose up -d --force-recreate collector
curl http://localhost:8060/health
```
