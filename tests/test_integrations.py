"""
Integration-style tests covering the full pipeline flow
(all external API calls are mocked).
"""

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_TMP = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/integration.db"
os.environ["APP_ENV"] = "dev"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """Set up a clean SQLite DB for each test."""
    import importlib
    import src.database as db_mod

    db_url = f"sqlite:///{tmp_path}/test_integration.db"
    db_mod.engine = db_mod.create_engine(
        db_url, connect_args={"check_same_thread": False}
    )
    db_mod.SessionLocal = db_mod.sessionmaker(bind=db_mod.engine)
    db_mod.Base.metadata.create_all(bind=db_mod.engine)
    yield
    db_mod.Base.metadata.drop_all(bind=db_mod.engine)


# ---------------------------------------------------------------------------
# config.validate_config
# ---------------------------------------------------------------------------

def test_validate_config_reports_missing(monkeypatch):
    import config

    for key in config.REQUIRED_KEYS:
        monkeypatch.delenv(key, raising=False)

    missing = config.validate_config()
    assert isinstance(missing, list)
    # Should report at least one missing key
    assert len(missing) > 0


def test_validate_config_passes_when_keys_set(monkeypatch):
    import config

    for key in config.REQUIRED_KEYS:
        monkeypatch.setenv(key, "fake-value")

    missing = config.validate_config()
    assert missing == []


# ---------------------------------------------------------------------------
# Trends → scripts pipeline
# ---------------------------------------------------------------------------

def _make_topics(n: int = 3) -> list[dict]:
    return [
        {
            "title": f"Topic {i}",
            "source": "youtube",
            "keywords": [f"kw{i}"],
            "view_count": 1_000_000,
            "engagement": 0.05,
            "score": float(10 - i),
        }
        for i in range(n)
    ]


def _make_script(title: str) -> dict:
    return {
        "title": title,
        "hook": "Hook text",
        "script": "Script body " * 50,
        "cta": "CTA text",
        "hashtags": ["#tag"],
        "seo_keywords": ["kw"],
        "thumbnail_description": "Thumbnail desc",
        "content_type": "educational",
        "topic": title,
        "source": "youtube",
        "generated_at": "2025-01-01T00:00:00+00:00",
    }


def test_pipeline_trends_to_database(tmp_path, monkeypatch):
    """
    Simulate: fetch trends → generate scripts → persist to DB.
    """
    import config
    import src.content_generator as cg
    import src.database as db_mod
    import src.trends as tr

    # Setup
    monkeypatch.setattr(config, "TRENDS_FILE", tmp_path / "trends.json")
    monkeypatch.setattr(config, "SCRIPTS_FILE", tmp_path / "scripts.json")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test")

    # --- Step 1: Mock trends ---
    topics = _make_topics(3)

    async def mock_yt():
        return topics

    async def mock_reddit():
        return []

    async def mock_gt():
        return []

    monkeypatch.setattr(tr, "_fetch_youtube_trending", mock_yt)
    monkeypatch.setattr(tr, "_fetch_reddit_trending", mock_reddit)
    monkeypatch.setattr(tr, "_fetch_google_trends", mock_gt)

    fetched = asyncio.run(tr.fetch_trends(force=True))
    assert len(fetched) == 3

    # --- Step 2: Mock script generation ---
    scripts = [_make_script(t["title"]) for t in fetched]

    # Persist to DB manually (mirrors scheduler behaviour)
    db_ids = []
    for script in scripts:
        v = db_mod.create_video(
            title=script["title"],
            script=script["script"],
            hashtags=", ".join(script.get("hashtags", [])),
            seo_keywords=", ".join(script.get("seo_keywords", [])),
            content_type=script.get("content_type", "educational"),
        )
        db_ids.append(v.id)

    assert len(db_ids) == 3

    # --- Step 3: Verify DB state ---
    with db_mod.get_session() as session:
        videos = session.query(db_mod.Video).all()
        assert len(videos) == 3
        for v in videos:
            assert v.status == "pending"


def test_analytics_collect_daily_stats(tmp_path, monkeypatch):
    """collect_daily_stats should aggregate completed videos correctly."""
    from datetime import date, datetime, timedelta, timezone

    import src.analytics as analytics
    import src.database as db_mod

    monkeypatch.setattr(analytics.config, "DATABASE_URL", db_mod.engine.url)

    # Create some videos
    for i in range(5):
        v = db_mod.create_video(title=f"V{i}", script="S")
        db_mod.update_video_status(v.id, "completed", cost=1.0, duration=30.0)

    # Log some API calls
    db_mod.log_api_call("openai", "chat.completions", tokens_used=500, cost=0.05)
    db_mod.log_api_call("veo3", "generate_content", cost=4.5)

    stats = analytics.collect_daily_stats(date.today())
    assert stats["videos_completed"] == 5
    assert stats["total_cost"] > 0
    assert "openai" in stats["api_usage"]
