"""
Content Generation Module

Uses OpenAI ChatGPT API to generate 10 unique video scripts
based on the trending topics fetched by ``src/trends.py``.

Each script
-----------
- 500–800 words
- Optimised for YouTube / TikTok / Instagram Reels
- Includes hook, body, CTA, storytelling elements
- Comes with custom hashtags and SEO keywords
- Categorised as educational / entertainment / motivational

Output
------
Writes ``data/scripts.json`` with a list of script dicts.
"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timezone
from typing import Any

import config
from src.database import log_api_call
from src.logger import get_logger
from src.utils import async_retry, save_json

logger = get_logger(__name__)

CONTENT_TYPES = ["educational", "entertainment", "motivational"]

_SYSTEM_PROMPT = """
You are an expert YouTube/TikTok/Instagram content creator with 10M+ followers.
You specialise in writing viral, engaging video scripts that hook viewers in the
first 3 seconds and retain them until the end.

Respond ONLY with valid JSON in the following schema:
{
  "title": "string – catchy, SEO-optimised video title (max 70 chars)",
  "hook": "string – opening 1-2 sentences that immediately grab attention",
  "script": "string – full 500-800 word video script",
  "cta": "string – clear call-to-action at the end",
  "hashtags": ["string", ...],
  "seo_keywords": ["string", ...],
  "thumbnail_description": "string – describe the ideal thumbnail image"
}
""".strip()


def _build_user_prompt(topic: dict[str, Any], content_type: str) -> str:
    keywords = ", ".join(topic.get("keywords", [])[:5]) or topic["title"]
    return (
        f"Create a {content_type} video script about: \"{topic['title']}\".\n"
        f"Focus keywords: {keywords}.\n"
        f"The video is for YouTube Shorts / TikTok / Instagram Reels (vertical format).\n"
        f"Include a compelling hook in the first 3 seconds, storytelling elements, "
        f"engagement tactics (ask a question, give a tip, share a shocking fact), "
        f"and a strong CTA at the end.\n"
        f"Provide exactly 5–10 hashtags and 5–8 SEO keywords."
    )


# ---------------------------------------------------------------------------
# Single script generation
# ---------------------------------------------------------------------------


@async_retry(max_attempts=3, initial_delay=2.0, exceptions=(Exception,))
async def _generate_script(
    client: Any,
    topic: dict[str, Any],
    content_type: str,
) -> dict[str, Any]:
    """Call the ChatGPT API and return a parsed script dict."""
    prompt = _build_user_prompt(topic, content_type)

    response = await client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.8,
        max_tokens=1200,
        response_format={"type": "json_object"},
    )

    usage = response.usage
    cost = _estimate_openai_cost(usage.prompt_tokens, usage.completion_tokens)
    log_api_call(
        service="openai",
        endpoint="chat.completions",
        tokens_used=usage.total_tokens,
        cost=cost,
        success=True,
    )

    raw = response.choices[0].message.content
    data: dict[str, Any] = json.loads(raw)
    data["topic"] = topic["title"]
    data["source"] = topic.get("source", "unknown")
    data["content_type"] = content_type
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    data.setdefault("hashtags", [])
    data.setdefault("seo_keywords", [])
    data.setdefault("thumbnail_description", "")
    return data


def _estimate_openai_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Rough cost estimate for GPT-4o ($/1K tokens)."""
    cost = (prompt_tokens / 1000) * 0.005 + (completion_tokens / 1000) * 0.015
    return round(cost, 6)


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------


async def generate_scripts(
    topics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Generate one script per topic in parallel using asyncio.

    Parameters
    ----------
    topics:
        List of trending topic dicts as returned by ``src.trends.fetch_trends``.

    Returns
    -------
    list[dict]
        List of generated script dicts; failed items are excluded.
    """
    if not config.OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set – cannot generate scripts")
        return []

    from openai import AsyncOpenAI  # type: ignore

    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

    # Distribute content types across topics
    types_cycle = (CONTENT_TYPES * ((len(topics) // len(CONTENT_TYPES)) + 1))[
        : len(topics)
    ]
    random.shuffle(types_cycle)

    logger.info("Generating %d scripts in parallel…", len(topics))
    tasks = [
        _generate_script(client, topic, content_type)
        for topic, content_type in zip(topics, types_cycle)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    scripts: list[dict[str, Any]] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(
                "Script generation failed for topic %d (%s): %s",
                i,
                topics[i].get("title", "?"),
                result,
            )
        else:
            scripts.append(result)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(scripts),
        "scripts": scripts,
    }
    save_json(payload, config.SCRIPTS_FILE)
    logger.info("Scripts generated and saved: %d/%d", len(scripts), len(topics))
    return scripts
