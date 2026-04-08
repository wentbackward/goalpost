import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TZDateTime = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("platform", "platform_post_id", name="uq_platform_post"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    postiz_post_id: Mapped[str | None] = mapped_column()
    platform: Mapped[str] = mapped_column()
    platform_post_id: Mapped[str] = mapped_column()
    content_text: Mapped[str | None] = mapped_column(Text)
    media_url: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str | None] = mapped_column()
    published_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    metrics: Mapped[list["PostMetric"]] = relationship(back_populates="post")
    hashtags: Mapped[list["PostHashtag"]] = relationship(back_populates="post")


class PostHashtag(Base):
    __tablename__ = "post_hashtags"
    __table_args__ = (
        Index("ix_post_hashtags_hashtag", "hashtag"),
        UniqueConstraint("post_id", "hashtag", name="uq_post_hashtag"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analytics.posts.id", ondelete="CASCADE")
    )
    hashtag: Mapped[str] = mapped_column()

    post: Mapped["Post"] = relationship(back_populates="hashtags")


class PostMetric(Base):
    __tablename__ = "post_metrics"
    __table_args__ = (
        Index("ix_post_metrics_post_id_synced", "post_id", "synced_at"),
        {"schema": "analytics"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analytics.posts.id", ondelete="CASCADE")
    )
    synced_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(timezone.utc)
    )
    impressions: Mapped[int | None] = mapped_column(BigInteger)
    reach: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    shares: Mapped[int | None] = mapped_column(BigInteger)
    saves: Mapped[int | None] = mapped_column(BigInteger)
    clicks: Mapped[int | None] = mapped_column(BigInteger)
    video_views: Mapped[int | None] = mapped_column(BigInteger)
    video_watch_time_ms: Mapped[int | None] = mapped_column(BigInteger)
    raw: Mapped[dict | None] = mapped_column(JSONB)

    post: Mapped["Post"] = relationship(back_populates="metrics")


class SyncLog(Base):
    __tablename__ = "sync_log"
    __table_args__ = {"schema": "analytics"}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    triggered_at: Mapped[datetime] = mapped_column(
        TZDateTime, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    platform: Mapped[str | None] = mapped_column()
    status: Mapped[str] = mapped_column(default="running")
    posts_synced: Mapped[int] = mapped_column(default=0)
    posts_failed: Mapped[int] = mapped_column(default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column()
