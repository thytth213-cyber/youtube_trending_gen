"""
Tests for src/trends.py
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

# Minimal env so config doesn't crash
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/test_trends.db")
os.environ.setdefault("APP_ENV", "dev")


# ---------------------------------------------------------------------------

def _sample_topic(title: str, source: str = "youtube", score: float = 5.0) -> dict:
    return {
        "title": title,
        "source": source,
        "keywords": [title.lower()],
        "view_count": 1_000_000,
        "engagement": 0.05,
        "score": score,
    }


# ── Cache logic ───────────────────────────────────────────────────────────────

def test_fetch_trends_returns_cached_data(tmp_path):
    """fetch_trends should return cached topics when cache is fresh."""
    import src.trends as trends_mod
    import config

    # Write fresh cache
    topics = [_sample_topic(f"Topic {i}", score=float(10 - i)) for i in range(10)]
    cache = {"fetched_at": time.time(), "topics": topics}
    cache_file = tmp_path / "trends.json"
    cache_file.write_text(json.dumps(cache))

    # Patch config paths
    orig_trends_file = config.TRENDS_FILE
    config.TRENDS_FILE = cache_file
    try:
        result = asyncio.run(trends_mod.fetch_trends(force=False))
        assert len(result) == 10
        assert result[0]["title"] == "Topic 0"
    finally:
        config.TRENDS_FILE = orig_trends_file


def test_fetch_trends_ignores_stale_cache(tmp_path, monkeypatch):
    """fetch_trends should bypass cache when it is too old."""
    import src.trends as trends_mod
    import config

    # Write stale cache (25 hours old)
    topics = [_sample_topic("Old topic")]
    cache = {"fetched_at": time.time() - 25 * 3600, "topics": topics}
    cache_file = tmp_path / "trends.json"
    cache_file.write_text(json.dumps(cache))

    config.TRENDS_FILE = cache_file

    fresh_topics = [_sample_topic(f"Fresh {i}", score=float(10 - i)) for i in range(10)]

    async def mock_yt():
        return fresh_topics[:5]

    async def mock_reddit():
        return fresh_topics[5:]

    async def mock_gt():
        return []

    monkeypatch.setattr(trends_mod, "_fetch_youtube_trending", mock_yt)
    monkeypatch.setattr(trends_mod, "_fetch_reddit_trending", mock_reddit)
    monkeypatch.setattr(trends_mod, "_fetch_google_trends", mock_gt)

    result = asyncio.run(trends_mod.fetch_trends(force=False))
    assert any("Fresh" in t["title"] for t in result)

    # restore
    import importlib
    import src.trends
    config.TRENDS_FILE = Path("/app/data/trends.json")


def test_fetch_trends_deduplicates(tmp_path, monkeypatch):
    """Duplicate titles (case-insensitive) should be removed."""
    import src.trends as trends_mod
    import config

    config.TRENDS_FILE = tmp_path / "trends.json"

    dup_topics = [_sample_topic("AI Revolution")] * 5

    async def mock_yt():
        return dup_topics

    async def mock_reddit():
        return [_sample_topic("ai revolution")]  # same title, lowercase

    async def mock_gt():
        return []

    monkeypatch.setattr(trends_mod, "_fetch_youtube_trending", mock_yt)
    monkeypatch.setattr(trends_mod, "_fetch_reddit_trending", mock_reddit)
    monkeypatch.setattr(trends_mod, "_fetch_google_trends", mock_gt)

    result = asyncio.run(trends_mod.fetch_trends(force=True))
    titles = [t["title"].lower() for t in result]
    assert titles.count("ai revolution") == 1

    config.TRENDS_FILE = Path("/app/data/trends.json")


def test_fetch_trends_returns_at_most_10(tmp_path, monkeypatch):
    """Output should be capped at 10 topics."""
    import src.trends as trends_mod
    import config

    config.TRENDS_FILE = tmp_path / "trends.json"

    many = [_sample_topic(f"Topic {i}", score=float(100 - i)) for i in range(50)]

    async def mock_all():
        return many

    async def mock_reddit():
        return []

    async def mock_gt():
        return []

    monkeypatch.setattr(trends_mod, "_fetch_youtube_trending", mock_all)
    monkeypatch.setattr(trends_mod, "_fetch_reddit_trending", mock_reddit)
    monkeypatch.setattr(trends_mod, "_fetch_google_trends", mock_gt)

    result = asyncio.run(trends_mod.fetch_trends(force=True))
    assert len(result) <= 10

    config.TRENDS_FILE = Path("/app/data/trends.json")
