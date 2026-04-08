import uuid
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth import require_api_key
from ..database import get_session
from ..models import Post, PostMetric
from ..schemas import (
    AnalyticsSummaryResponse,
    MetricSnapshot,
    PlatformTotals,
    PostListResponse,
    PostMetricsResponse,
    PostRegisterRequest,
    PostResponse,
    TopPost,
)

router = APIRouter(tags=["analytics"])
logger = structlog.get_logger()


def _post_to_response(post: Post, latest_metric: PostMetric | None = None) -> PostResponse:
    latest = None
    if latest_metric:
        latest = MetricSnapshot.model_validate(latest_metric)
    return PostResponse(
        id=post.id,
        postiz_post_id=post.postiz_post_id,
        platform=post.platform,
        platform_post_id=post.platform_post_id,
        content_text=post.content_text,
        media_type=post.media_type,
        published_at=post.published_at,
        created_at=post.created_at,
        updated_at=post.updated_at,
        latest_metrics=latest,
    )


@router.post("/posts/register", response_model=PostResponse)
async def register_post(
    body: PostRegisterRequest,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_api_key),
):
    post = Post(
        platform=body.platform,
        platform_post_id=body.platform_post_id,
        content_text=body.content_text,
        media_type=body.media_type,
        published_at=body.published_at,
    )
    session.add(post)
    await session.commit()
    await session.refresh(post)
    return _post_to_response(post)


@router.get("/posts", response_model=PostListResponse)
async def list_posts(
    platform: str | None = None,
    media_type: str | None = None,
    published_after: datetime | None = None,
    published_before: datetime | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_api_key),
):
    conditions = []
    if platform:
        conditions.append(Post.platform == platform)
    if media_type:
        conditions.append(Post.media_type == media_type)
    if published_after:
        conditions.append(Post.published_at >= published_after)
    if published_before:
        conditions.append(Post.published_at <= published_before)

    where = and_(*conditions) if conditions else True

    count_stmt = select(func.count(Post.id)).where(where)
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = (
        select(Post)
        .where(where)
        .order_by(desc(Post.published_at))
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    posts = result.scalars().all()

    # Get latest metric for each post
    responses = []
    for post in posts:
        metric_stmt = (
            select(PostMetric)
            .where(PostMetric.post_id == post.id)
            .order_by(desc(PostMetric.synced_at))
            .limit(1)
        )
        metric = (await session.execute(metric_stmt)).scalar_one_or_none()
        responses.append(_post_to_response(post, metric))

    return PostListResponse(posts=responses, total=total, limit=limit, offset=offset)


@router.get("/posts/{post_id}/metrics", response_model=PostMetricsResponse)
async def get_post_metrics(
    post_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_api_key),
):
    post = await session.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    stmt = (
        select(PostMetric)
        .where(PostMetric.post_id == post_id)
        .order_by(PostMetric.synced_at)
    )
    result = await session.execute(stmt)
    metrics = result.scalars().all()

    latest = metrics[-1] if metrics else None

    return PostMetricsResponse(
        post=_post_to_response(post, latest),
        metrics=[MetricSnapshot.model_validate(m) for m in metrics],
    )


@router.get("/analytics/summary", response_model=AnalyticsSummaryResponse)
async def analytics_summary(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    platform: str | None = None,
    media_type: str | None = None,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_api_key),
):
    # Build post filters
    post_conditions = []
    if platform:
        post_conditions.append(Post.platform == platform)
    if media_type:
        post_conditions.append(Post.media_type == media_type)
    if start_date:
        post_conditions.append(Post.published_at >= start_date)
    if end_date:
        post_conditions.append(Post.published_at <= end_date)

    post_where = and_(*post_conditions) if post_conditions else True
    posts_stmt = select(Post).where(post_where)
    posts_result = await session.execute(posts_stmt)
    posts = posts_result.scalars().all()

    # For each post, get the latest metric snapshot
    totals = PlatformTotals(posts=len(posts))
    by_platform: dict[str, PlatformTotals] = {}
    by_media_type: dict[str, PlatformTotals] = {}
    top_posts_data: list[tuple[Post, PostMetric]] = []

    for post in posts:
        metric_stmt = (
            select(PostMetric)
            .where(PostMetric.post_id == post.id)
            .order_by(desc(PostMetric.synced_at))
            .limit(1)
        )
        metric = (await session.execute(metric_stmt)).scalar_one_or_none()
        if not metric:
            continue

        top_posts_data.append((post, metric))

        # Aggregate totals
        totals.impressions += metric.impressions or 0
        totals.likes += metric.likes or 0
        totals.comments += metric.comments or 0
        totals.shares += metric.shares or 0
        totals.video_views += metric.video_views or 0

        # By platform
        plat = by_platform.setdefault(post.platform, PlatformTotals())
        plat.posts += 1
        plat.impressions += metric.impressions or 0
        plat.likes += metric.likes or 0
        plat.comments += metric.comments or 0
        plat.shares += metric.shares or 0
        plat.video_views += metric.video_views or 0

        # By media type
        mt = post.media_type or "unknown"
        media = by_media_type.setdefault(mt, PlatformTotals())
        media.posts += 1
        media.impressions += metric.impressions or 0
        media.likes += metric.likes or 0
        media.comments += metric.comments or 0
        media.shares += metric.shares or 0
        media.video_views += metric.video_views or 0

    # Top posts by impressions
    top_posts_data.sort(key=lambda x: x[1].impressions or 0, reverse=True)
    top_posts = []
    for post, metric in top_posts_data[:10]:
        imp = metric.impressions or 0
        engagement = (metric.likes or 0) + (metric.comments or 0) + (metric.shares or 0)
        rate = engagement / imp if imp > 0 else 0.0
        top_posts.append(TopPost(
            post_id=post.id,
            platform=post.platform,
            published_at=post.published_at,
            impressions=imp,
            engagement_rate=round(rate, 6),
        ))

    return AnalyticsSummaryResponse(
        period={
            "start": start_date.isoformat() if start_date else "",
            "end": end_date.isoformat() if end_date else "",
        },
        totals=totals,
        by_platform=by_platform,
        by_media_type=by_media_type,
        top_posts=top_posts,
    )
