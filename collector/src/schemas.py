import uuid
from datetime import datetime

from pydantic import BaseModel


# --- Sync ---

class SyncResponse(BaseModel):
    sync_id: uuid.UUID
    platforms_triggered: list[str]
    platforms_skipped: list[str]
    status: str


class SyncStatusResponse(BaseModel):
    sync_id: uuid.UUID
    status: str
    triggered_at: datetime
    completed_at: datetime | None = None
    posts_synced: int
    posts_failed: int
    error_summary: str | None = None
    duration_ms: int | None = None


# --- Posts ---

class PostRegisterRequest(BaseModel):
    platform: str
    platform_post_id: str
    content_text: str | None = None
    media_type: str | None = None
    published_at: datetime | None = None


class MetricSnapshot(BaseModel):
    synced_at: datetime
    impressions: int | None = None
    reach: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    clicks: int | None = None
    video_views: int | None = None
    video_watch_time_ms: int | None = None

    model_config = {"from_attributes": True}


class PostResponse(BaseModel):
    id: uuid.UUID
    postiz_post_id: str | None = None
    platform: str
    platform_post_id: str
    content_text: str | None = None
    media_type: str | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    latest_metrics: MetricSnapshot | None = None

    model_config = {"from_attributes": True}


class PostMetricsResponse(BaseModel):
    post: PostResponse
    metrics: list[MetricSnapshot]


class PostListResponse(BaseModel):
    posts: list[PostResponse]
    total: int
    limit: int
    offset: int


# --- Analytics ---

class PlatformTotals(BaseModel):
    posts: int = 0
    impressions: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    video_views: int = 0


class TopPost(BaseModel):
    post_id: uuid.UUID
    platform: str
    published_at: datetime | None = None
    impressions: int = 0
    engagement_rate: float = 0.0


class AnalyticsSummaryResponse(BaseModel):
    period: dict[str, str]
    totals: PlatformTotals
    by_platform: dict[str, PlatformTotals]
    by_media_type: dict[str, PlatformTotals]
    top_posts: list[TopPost]


# --- Health ---

class HealthResponse(BaseModel):
    status: str
    db: str
    providers: dict[str, str]
