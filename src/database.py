"""
SQLite database module using SQLAlchemy ORM.

Tables
------
videos        – video records with scripts, statuses, and cost tracking
thumbnails    – thumbnail file records linked to videos
social_posts  – Buffer-scheduled / posted items
daily_stats   – aggregated daily metrics
api_logs      – per-call API usage and cost
"""

import json
import shutil
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

import config
from src.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine & Session
# ---------------------------------------------------------------------------

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=(config.APP_ENV == "dev"),
)

# Enable WAL mode for better concurrent read performance
@event.listens_for(engine, "connect")
def _set_wal_mode(dbapi_conn, _connection_record):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_session() -> Session:
    """Return a new database session (caller is responsible for closing it)."""
    return SessionLocal()


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    script = Column(Text, nullable=False)
    veo3_id = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    cost = Column(Float, nullable=False, default=0.0)
    duration = Column(Float, nullable=True)  # seconds
    filepath = Column(String(512), nullable=True)
    hashtags = Column(Text, nullable=True)
    seo_keywords = Column(Text, nullable=True)
    content_type = Column(String(50), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    thumbnails = relationship(
        "Thumbnail", back_populates="video", cascade="all, delete-orphan"
    )
    social_posts = relationship(
        "SocialPost", back_populates="video", cascade="all, delete-orphan"
    )


class Thumbnail(Base):
    __tablename__ = "thumbnails"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"))
    filepath = Column(String(512), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    video = relationship("Video", back_populates="thumbnails")


class SocialPost(Base):
    __tablename__ = "social_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="CASCADE"))
    platform = Column(String(50), nullable=False)
    url = Column(String(512), nullable=True)
    scheduled_time = Column(DateTime(timezone=True), nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True)
    buffer_id = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="scheduled")

    video = relationship("Video", back_populates="social_posts")


class DailyStat(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, unique=True)
    videos_count = Column(Integer, nullable=False, default=0)
    total_cost = Column(Float, nullable=False, default=0.0)
    estimated_revenue = Column(Float, nullable=False, default=0.0)
    api_usage_json = Column(Text, nullable=True)  # JSON string


class ApiLog(Base):
    __tablename__ = "api_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service = Column(String(100), nullable=False)
    endpoint = Column(String(255), nullable=False)
    tokens_used = Column(Integer, nullable=True)
    cost = Column(Float, nullable=False, default=0.0)
    timestamp = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    success = Column(Integer, nullable=False, default=1)  # 1=True, 0=False
    notes = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Initialisation & Backup
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create all tables (idempotent – safe to call on every startup)."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialised → %s", config.DATABASE_URL)


def backup_db() -> bool:
    """Copy the SQLite database file to the backup path."""
    try:
        db_path_str = config.DATABASE_URL.replace("sqlite:///", "")
        backup_path = config.DB_BACKUP_FILE
        shutil.copy2(db_path_str, str(backup_path))
        logger.info("Database backed up → %s", backup_path)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Database backup failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------


def create_video(
    title: str,
    script: str,
    hashtags: str = "",
    seo_keywords: str = "",
    content_type: str = "educational",
) -> Video:
    with get_session() as session:
        video = Video(
            title=title,
            script=script,
            hashtags=hashtags,
            seo_keywords=seo_keywords,
            content_type=content_type,
        )
        session.add(video)
        session.commit()
        session.refresh(video)
        logger.debug("Created video id=%d title=%s", video.id, video.title)
        return video


def update_video_status(
    video_id: int,
    status: str,
    veo3_id: str | None = None,
    filepath: str | None = None,
    cost: float | None = None,
    duration: float | None = None,
) -> bool:
    with get_session() as session:
        video = session.get(Video, video_id)
        if not video:
            logger.warning("update_video_status: video id=%d not found", video_id)
            return False
        video.status = status
        if veo3_id is not None:
            video.veo3_id = veo3_id
        if filepath is not None:
            video.filepath = filepath
        if cost is not None:
            video.cost = cost
        if duration is not None:
            video.duration = duration
        session.commit()
        return True


def log_api_call(
    service: str,
    endpoint: str,
    tokens_used: int | None = None,
    cost: float = 0.0,
    success: bool = True,
    notes: str | None = None,
) -> None:
    with get_session() as session:
        log = ApiLog(
            service=service,
            endpoint=endpoint,
            tokens_used=tokens_used,
            cost=cost,
            success=int(success),
            notes=notes,
        )
        session.add(log)
        session.commit()


def upsert_daily_stats(
    day: date,
    videos_count: int = 0,
    total_cost: float = 0.0,
    estimated_revenue: float = 0.0,
    api_usage: dict | None = None,
) -> None:
    with get_session() as session:
        stat = session.query(DailyStat).filter_by(date=day).first()
        if stat is None:
            stat = DailyStat(date=day)
            session.add(stat)
        stat.videos_count = videos_count
        stat.total_cost = total_cost
        stat.estimated_revenue = estimated_revenue
        stat.api_usage_json = json.dumps(api_usage or {})
        session.commit()
