"""
Tests for src/database.py
"""

import os
import sys
import tempfile
from datetime import date, datetime, timezone

import pytest

# Point to a temporary SQLite DB for tests
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["APP_ENV"] = "dev"

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import config  # noqa: E402 (import after env setup)

# Patch config to use temp paths
config.DATABASE_URL = f"sqlite:///{_tmp}/test.db"
config.DATA_DIR = type("P", (), {"__truediv__": lambda s, x: type("P2", (), {"__str__": lambda s2: f"{_tmp}/{x}"})()})()


from src.database import (  # noqa: E402
    ApiLog,
    DailyStat,
    Thumbnail,
    Video,
    backup_db,
    create_video,
    get_session,
    init_db,
    log_api_call,
    update_video_status,
    upsert_daily_stats,
)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Re-create the DB schema before each test."""
    import importlib
    import src.database as db_mod

    db_mod.engine = db_mod.create_engine(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
    )
    db_mod.SessionLocal = db_mod.sessionmaker(bind=db_mod.engine)
    db_mod.Base.metadata.create_all(bind=db_mod.engine)
    yield
    db_mod.Base.metadata.drop_all(bind=db_mod.engine)


# ── Video CRUD ───────────────────────────────────────────────────────────────

def test_create_video_returns_video(fresh_db):
    import src.database as db_mod

    video = db_mod.create_video(
        title="Test Video",
        script="This is a test script.",
        hashtags="#test",
        seo_keywords="test,video",
        content_type="educational",
    )
    assert video.id is not None
    assert video.title == "Test Video"
    assert video.status == "pending"


def test_update_video_status(fresh_db):
    import src.database as db_mod

    video = db_mod.create_video(title="V", script="S")
    result = db_mod.update_video_status(
        video.id,
        "completed",
        veo3_id="veo-abc",
        filepath="/app/data/videos/v.mp4",
        cost=2.5,
        duration=30.0,
    )
    assert result is True

    with db_mod.get_session() as session:
        v = session.get(db_mod.Video, video.id)
        assert v.status == "completed"
        assert v.veo3_id == "veo-abc"
        assert v.cost == 2.5
        assert v.duration == 30.0


def test_update_video_status_not_found(fresh_db):
    import src.database as db_mod

    result = db_mod.update_video_status(9999, "completed")
    assert result is False


# ── API logging ──────────────────────────────────────────────────────────────

def test_log_api_call(fresh_db):
    import src.database as db_mod

    db_mod.log_api_call(
        service="openai",
        endpoint="chat.completions",
        tokens_used=500,
        cost=0.025,
        success=True,
    )
    with db_mod.get_session() as session:
        logs = session.query(db_mod.ApiLog).all()
        assert len(logs) == 1
        assert logs[0].service == "openai"
        assert logs[0].tokens_used == 500


# ── Daily stats ───────────────────────────────────────────────────────────────

def test_upsert_daily_stats_creates_and_updates(fresh_db):
    import src.database as db_mod

    today = date.today()
    db_mod.upsert_daily_stats(today, videos_count=5, total_cost=1.5, estimated_revenue=3.0)
    db_mod.upsert_daily_stats(today, videos_count=10, total_cost=2.0, estimated_revenue=5.0)

    with db_mod.get_session() as session:
        stats = session.query(db_mod.DailyStat).filter_by(date=today).all()
        assert len(stats) == 1
        assert stats[0].videos_count == 10
        assert stats[0].total_cost == 2.0


# ── Thumbnail relationship ───────────────────────────────────────────────────

def test_thumbnail_relationship(fresh_db):
    import src.database as db_mod

    video = db_mod.create_video(title="VT", script="S")
    with db_mod.get_session() as session:
        thumb = db_mod.Thumbnail(video_id=video.id, filepath="/app/data/thumbnails/t.png")
        session.add(thumb)
        session.commit()

    with db_mod.get_session() as session:
        v = session.get(db_mod.Video, video.id)
        assert len(v.thumbnails) == 1
        assert v.thumbnails[0].filepath == "/app/data/thumbnails/t.png"
