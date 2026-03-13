"""
Tests for src/video_generator.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/test_video.db")
os.environ.setdefault("APP_ENV", "dev")


def _sample_script(title: str = "Best Video Ever") -> dict:
    return {
        "title": title,
        "hook": "Watch this!",
        "script": "This is a great script. " * 30,
        "cta": "Subscribe!",
        "hashtags": ["#video", "#ai"],
        "seo_keywords": ["video", "ai"],
        "thumbnail_description": "A bright thumbnail",
        "content_type": "educational",
    }


# ── _build_veo_prompt ─────────────────────────────────────────────────────────

def test_build_veo_prompt_contains_title():
    from src.video_generator import _build_veo_prompt

    script = _sample_script("Epic AI Video")
    prompt = _build_veo_prompt(script)
    assert "Epic AI Video" in prompt
    assert "9:16" in prompt


def test_build_veo_prompt_includes_content_type_style():
    from src.video_generator import _build_veo_prompt

    for ct in ["educational", "entertainment", "motivational"]:
        script = _sample_script()
        script["content_type"] = ct
        prompt = _build_veo_prompt(script)
        assert len(prompt) > 50  # non-trivial prompt


# ── generate_videos – no API key ─────────────────────────────────────────────

def test_generate_videos_no_api_key(monkeypatch):
    import config
    import src.video_generator as vg

    monkeypatch.setattr(config, "GOOGLE_VEO3_API_KEY", "")

    async def run():
        return await vg.generate_videos([(_sample_script(), 1)])

    with patch("src.video_generator.update_video_status"):
        result = asyncio.run(run())
    assert result == []


# ── generate_videos – mocked success ─────────────────────────────────────────

def test_generate_videos_mocked_success(monkeypatch, tmp_path):
    import config
    import src.video_generator as vg

    monkeypatch.setattr(config, "GOOGLE_VEO3_API_KEY", "fake-key")
    monkeypatch.setattr(config, "VIDEOS_DIR", tmp_path)
    monkeypatch.setattr(config, "VEO3_COST_PER_SECOND", 0.15)

    # Build a mock Veo 3 response with fake video bytes
    fake_bytes = b"\x00" * 500_000  # 500 KB

    mock_part = MagicMock()
    mock_part.inline_data = MagicMock(data=fake_bytes)

    mock_response = MagicMock()
    mock_response.parts = [mock_part]
    mock_response.done = MagicMock(return_value=True)
    mock_response.operation_name = "op-123"

    mock_model = MagicMock()
    mock_model.generate_content = MagicMock(return_value=mock_response)

    mock_genai = MagicMock()
    mock_genai.GenerativeModel = MagicMock(return_value=mock_model)

    with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
        with patch("src.video_generator.update_video_status"):
            with patch("src.video_generator.log_api_call"):
                result = asyncio.run(
                    vg.generate_videos([(_sample_script(), 42)])
                )

    assert len(result) == 1
    assert result[0]["video_id"] == 42
    assert result[0]["cost"] > 0


# ── generate_videos – handles failure ────────────────────────────────────────

def test_generate_videos_marks_failed_on_error(monkeypatch, tmp_path):
    import config
    import src.video_generator as vg

    monkeypatch.setattr(config, "GOOGLE_VEO3_API_KEY", "fake-key")
    monkeypatch.setattr(config, "VIDEOS_DIR", tmp_path)

    mock_genai = MagicMock()
    mock_genai.GenerativeModel.side_effect = RuntimeError("API failure")

    status_updates = []

    def mock_update(vid_id, status, **kwargs):
        status_updates.append((vid_id, status))
        return True

    with patch.dict("sys.modules", {"google.generativeai": mock_genai}):
        with patch("src.video_generator.update_video_status", side_effect=mock_update):
            with patch("src.video_generator.log_api_call"):
                result = asyncio.run(
                    vg.generate_videos([(_sample_script(), 99)])
                )

    assert result == []
    # Should have called update_video_status with "failed"
    assert any(s == "failed" for _, s in status_updates)
