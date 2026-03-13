"""
Tests for src/content_generator.py
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/test_content.db")
os.environ.setdefault("APP_ENV", "dev")


def _sample_topic(title: str = "AI Trends 2025") -> dict:
    return {
        "title": title,
        "source": "youtube",
        "keywords": ["ai", "trends", "2025"],
        "view_count": 5_000_000,
        "engagement": 0.06,
        "score": 9.5,
    }


def _mock_openai_response(title: str = "Test Title") -> MagicMock:
    """Build a fake OpenAI chat completion response."""
    script_data = {
        "title": title,
        "hook": "Did you know AI is changing everything?",
        "script": "Body text " * 60,  # ~600 words
        "cta": "Subscribe now!",
        "hashtags": ["#AI", "#Tech", "#Future"],
        "seo_keywords": ["AI", "technology", "trends"],
        "thumbnail_description": "Bright colourful infographic on AI",
    }
    msg = MagicMock()
    msg.content = json.dumps(script_data)

    choice = MagicMock()
    choice.message = msg

    usage = MagicMock()
    usage.prompt_tokens = 200
    usage.completion_tokens = 400
    usage.total_tokens = 600

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


# ── _build_user_prompt ────────────────────────────────────────────────────────

def test_build_user_prompt_contains_title():
    from src.content_generator import _build_user_prompt

    topic = _sample_topic("Machine Learning Explained")
    prompt = _build_user_prompt(topic, "educational")
    assert "Machine Learning Explained" in prompt
    assert "educational" in prompt


def test_build_user_prompt_contains_keywords():
    from src.content_generator import _build_user_prompt

    topic = _sample_topic()
    prompt = _build_user_prompt(topic, "motivational")
    assert any(kw in prompt for kw in topic["keywords"])


# ── _estimate_openai_cost ─────────────────────────────────────────────────────

def test_estimate_openai_cost_positive():
    from src.content_generator import _estimate_openai_cost

    cost = _estimate_openai_cost(500, 400)
    assert cost > 0


def test_estimate_openai_cost_zero_tokens():
    from src.content_generator import _estimate_openai_cost

    cost = _estimate_openai_cost(0, 0)
    assert cost == 0.0


# ── generate_scripts (mocked) ─────────────────────────────────────────────────

def test_generate_scripts_no_api_key(monkeypatch):
    """Should return empty list when OPENAI_API_KEY is not set."""
    import config
    import src.content_generator as cg

    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    result = asyncio.run(cg.generate_scripts([_sample_topic()]))
    assert result == []


def test_generate_scripts_mocked_success(monkeypatch, tmp_path):
    """Should return one script per topic using a mocked OpenAI client."""
    import config
    import src.content_generator as cg

    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(config, "SCRIPTS_FILE", tmp_path / "scripts.json")

    mock_response = _mock_openai_response("Mocked Video")
    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    # AsyncOpenAI is imported locally inside generate_scripts, so patch via openai module
    with patch("openai.AsyncOpenAI", return_value=mock_client):
        # Also mock log_api_call so we don't need a real DB
        with patch("src.content_generator.log_api_call"):
            result = asyncio.run(cg.generate_scripts([_sample_topic()]))

    assert len(result) == 1
    assert result[0]["title"] == "Mocked Video"
    assert "content_type" in result[0]


def test_generate_scripts_handles_partial_failure(monkeypatch, tmp_path):
    """Failed API calls should be skipped; successful ones returned."""
    import config
    import src.content_generator as cg

    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(config, "SCRIPTS_FILE", tmp_path / "scripts.json")

    ok_response = _mock_openai_response("Good Video")
    call_count = 0

    async def flaky_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("API timeout")
        return ok_response

    mock_client = AsyncMock()
    mock_client.chat.completions.create = flaky_create

    topics = [_sample_topic("Topic A"), _sample_topic("Topic B")]

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        with patch("src.content_generator.log_api_call"):
            result = asyncio.run(cg.generate_scripts(topics))

    # Only the successful one should be returned
    assert len(result) >= 1
