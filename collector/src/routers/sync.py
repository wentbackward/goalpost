import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_api_key
from ..database import get_session
from ..models import Post, PostMetric, SyncLog
from ..providers import get_all_providers, get_configured_providers
from ..providers.base import ProviderError
from ..schemas import SyncResponse, SyncStatusResponse

router = APIRouter(tags=["sync"])
logger = structlog.get_logger()


async def _run_sync(sync_id: uuid.UUID, platforms: list[str] | None):
    """Background task that runs the actual sync."""
    from ..database import async_session

    async with async_session() as session:
        sync_log = await session.get(SyncLog, sync_id)
        if not sync_log:
            return

        start = datetime.now(timezone.utc)
        posts_synced = 0
        posts_failed = 0
        errors: list[str] = []

        # Discover new posts from Postiz before pulling metrics
        try:
            from ..postiz_bridge import sync_postiz_posts
            new_posts = await sync_postiz_posts(session, datetime.min.replace(tzinfo=timezone.utc))
            if new_posts:
                logger.info("sync.postiz_bridge", service="collector", sync_id=str(sync_id), new_posts=new_posts)
        except Exception as exc:
            logger.warning("sync.postiz_bridge_failed", service="collector", sync_id=str(sync_id), error=str(exc))

        # Parse hashtags for all posts that don't have any yet
        try:
            from ..hashtags import sync_post_hashtags
            all_posts_stmt = select(Post)
            all_posts = (await session.execute(all_posts_stmt)).scalars().all()
            for p in all_posts:
                await sync_post_hashtags(session, p)
            await session.commit()
        except Exception as exc:
            logger.warning("sync.hashtag_parse_failed", service="collector", sync_id=str(sync_id), error=str(exc))

        providers = await get_configured_providers()
        if platforms:
            providers = [p for p in providers if p.platform in platforms]

        for provider in providers:
            stmt = select(Post).where(Post.platform == provider.platform)
            result = await session.execute(stmt)
            posts = result.scalars().all()

            for post in posts:
                try:
                    metrics = await provider.fetch_metrics(post)
                    if metrics:
                        metric = PostMetric(
                            post_id=post.id,
                            synced_at=datetime.now(timezone.utc),
                            impressions=metrics.get("impressions"),
                            reach=metrics.get("reach"),
                            likes=metrics.get("likes"),
                            comments=metrics.get("comments"),
                            shares=metrics.get("shares"),
                            saves=metrics.get("saves"),
                            clicks=metrics.get("clicks"),
                            video_views=metrics.get("video_views"),
                            video_watch_time_ms=metrics.get("video_watch_time_ms"),
                            raw=metrics.get("raw"),
                        )
                        session.add(metric)
                        posts_synced += 1
                        logger.info(
                            "sync.post_success",
                            service="collector",
                            platform=provider.platform,
                            post_id=str(post.id),
                            sync_id=str(sync_id),
                        )
                except ProviderError as exc:
                    posts_failed += 1
                    errors.append(str(exc))
                    logger.error(
                        "sync.post_failed",
                        service="collector",
                        platform=provider.platform,
                        post_id=str(post.id),
                        sync_id=str(sync_id),
                        error=str(exc),
                    )
                except Exception as exc:
                    posts_failed += 1
                    errors.append(f"[{provider.platform}] {post.id}: {exc}")
                    logger.error(
                        "sync.post_unexpected_error",
                        service="collector",
                        platform=provider.platform,
                        post_id=str(post.id),
                        sync_id=str(sync_id),
                        error=str(exc),
                    )

        end = datetime.now(timezone.utc)
        sync_log.status = "completed" if not errors else "completed"
        sync_log.posts_synced = posts_synced
        sync_log.posts_failed = posts_failed
        sync_log.error_summary = "\n".join(errors) if errors else None
        sync_log.completed_at = end
        sync_log.duration_ms = int((end - start).total_seconds() * 1000)

        await session.commit()
        logger.info(
            "sync.completed",
            service="collector",
            sync_id=str(sync_id),
            posts_synced=posts_synced,
            posts_failed=posts_failed,
            duration_ms=sync_log.duration_ms,
        )


@router.post("/sync", response_model=SyncResponse)
async def trigger_sync(
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_api_key),
):
    all_providers = await get_all_providers()
    configured = await get_configured_providers()
    configured_names = {p.platform for p in configured}
    skipped_names = [p.platform for p in all_providers if p.platform not in configured_names]

    sync_log = SyncLog(platform=None, status="running")
    session.add(sync_log)
    await session.commit()
    await session.refresh(sync_log)

    background_tasks.add_task(_run_sync, sync_log.id, None)

    return SyncResponse(
        sync_id=sync_log.id,
        platforms_triggered=sorted(configured_names),
        platforms_skipped=sorted(skipped_names),
        status="started",
    )


@router.post("/sync/{platform}", response_model=SyncResponse)
async def trigger_platform_sync(
    platform: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_api_key),
):
    all_providers = await get_all_providers()
    provider_names = {p.platform for p in all_providers}
    if platform not in provider_names:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {platform}")

    configured = await get_configured_providers()
    configured_names = {p.platform for p in configured}
    is_configured = platform in configured_names

    sync_log = SyncLog(platform=platform, status="running")
    session.add(sync_log)
    await session.commit()
    await session.refresh(sync_log)

    if is_configured:
        background_tasks.add_task(_run_sync, sync_log.id, [platform])

    return SyncResponse(
        sync_id=sync_log.id,
        platforms_triggered=[platform] if is_configured else [],
        platforms_skipped=[platform] if not is_configured else [],
        status="started",
    )


@router.get("/sync/{sync_id}", response_model=SyncStatusResponse)
async def get_sync_status(
    sync_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(require_api_key),
):
    sync_log = await session.get(SyncLog, sync_id)
    if not sync_log:
        raise HTTPException(status_code=404, detail="Sync not found")

    return SyncStatusResponse(
        sync_id=sync_log.id,
        status=sync_log.status,
        triggered_at=sync_log.triggered_at,
        completed_at=sync_log.completed_at,
        posts_synced=sync_log.posts_synced,
        posts_failed=sync_log.posts_failed,
        error_summary=sync_log.error_summary,
        duration_ms=sync_log.duration_ms,
    )
