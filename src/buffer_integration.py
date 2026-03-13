"""
Buffer Integration Module

Schedules videos across social media platforms via the Buffer API:
- YouTube
- TikTok
- Instagram Reels
- Twitter/X

Each platform gets a platform-specific caption, hashtags, and an
optimised posting time.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx  # type: ignore

import config
from src.database import SocialPost, get_session, log_api_call
from src.logger import get_logger
from src.utils import async_retry

logger = get_logger(__name__)

_BUFFER_API_BASE = "https://api.bufferapp.com/1"

# Optimal posting offsets in hours from midnight UTC
_PLATFORM_OFFSETS: dict[str, int] = {
    "youtube": 14,      # 2 PM UTC
    "tiktok": 17,       # 5 PM UTC
    "instagram": 12,    # noon UTC
    "twitter": 9,       # 9 AM UTC
}

# Max caption lengths per platform
_CAPTION_LIMITS: dict[str, int] = {
    "youtube": 5000,
    "tiktok": 2200,
    "instagram": 2200,
    "twitter": 280,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_caption(
    script: dict[str, Any],
    platform: str,
) -> str:
    """Build a platform-specific caption from a script dict."""
    title = script.get("title", "")
    cta = script.get("cta", "")
    hashtags = script.get("hashtags", [])[:10]
    hashtag_str = " ".join(f"#{h.lstrip('#')}" for h in hashtags)

    if platform == "twitter":
        base = f"{title} {hashtag_str}"
    elif platform == "youtube":
        base = (
            f"{title}\n\n"
            f"{cta}\n\n"
            f"🔔 Subscribe for more!\n\n"
            f"{hashtag_str}"
        )
    else:  # tiktok / instagram
        base = (
            f"{title} ✨\n\n"
            f"{cta}\n\n"
            f"{hashtag_str}"
        )

    limit = _CAPTION_LIMITS.get(platform, 2200)
    return base[:limit]


def _scheduled_time(platform: str) -> datetime:
    """Return the next UTC datetime for posting on *platform*."""
    now = datetime.now(timezone.utc)
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    offset = _PLATFORM_OFFSETS.get(platform, 12)
    candidate = today_midnight + timedelta(hours=offset)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


# ---------------------------------------------------------------------------
# Single post scheduling
# ---------------------------------------------------------------------------


@async_retry(max_attempts=3, initial_delay=2.0, exceptions=(Exception,))
async def _schedule_post(
    video_id: int,
    video_filepath: str,
    script: dict[str, Any],
    platform: str,
    profile_id: str,
) -> dict[str, Any] | None:
    """Upload and schedule one post via the Buffer API."""
    caption = _build_caption(script, platform)
    scheduled_at = _scheduled_time(platform)

    payload = {
        "profile_ids[]": profile_id,
        "text": caption,
        "scheduled_at": scheduled_at.isoformat(),
        "media[video]": video_filepath,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{_BUFFER_API_BASE}/updates/create.json",
            headers={"Authorization": f"Bearer {config.BUFFER_API_TOKEN}"},
            data=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    updates = data.get("updates", [])
    if not updates:
        raise ValueError(f"Buffer API returned no updates for platform={platform}")
    buffer_id = updates[0].get("id", "")
    post_url = updates[0].get("profile_service_type", "")

    # Persist to database
    with get_session() as session:
        post = SocialPost(
            video_id=video_id,
            platform=platform,
            url=post_url,
            scheduled_time=scheduled_at,
            buffer_id=buffer_id,
            status="scheduled",
        )
        session.add(post)
        session.commit()

    log_api_call(
        service="buffer",
        endpoint="updates/create",
        cost=0.0,
        success=True,
        notes=f"platform={platform} video_id={video_id}",
    )
    logger.info("Scheduled %s post for video id=%d at %s", platform, video_id, scheduled_at)
    return {"platform": platform, "buffer_id": buffer_id, "scheduled_at": scheduled_at.isoformat()}


# ---------------------------------------------------------------------------
# Get Buffer profile IDs
# ---------------------------------------------------------------------------


async def _get_profile_ids() -> dict[str, str]:
    """
    Return a mapping of platform name → Buffer profile_id.
    Falls back to empty dict if the call fails.
    """
    if not config.BUFFER_API_TOKEN:
        return {}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_BUFFER_API_BASE}/profiles.json",
                headers={"Authorization": f"Bearer {config.BUFFER_API_TOKEN}"},
            )
            resp.raise_for_status()
            profiles = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch Buffer profiles: %s", exc)
        return {}

    mapping: dict[str, str] = {}
    for profile in profiles:
        service = profile.get("service", "").lower()
        pid = profile.get("id", "")
        if service in _PLATFORM_OFFSETS and pid:
            mapping[service] = pid
    return mapping


# ---------------------------------------------------------------------------
# Batch scheduling
# ---------------------------------------------------------------------------


async def schedule_posts(
    videos: list[dict[str, Any]],
    scripts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Schedule all completed videos across all configured Buffer platforms.

    Parameters
    ----------
    videos:
        List of video result dicts (with ``video_id`` and ``filepath``).
    scripts:
        Corresponding script dicts (same order as *videos*).

    Returns
    -------
    list[dict]
        Successfully scheduled post records.
    """
    if not config.BUFFER_API_TOKEN:
        logger.warning("BUFFER_API_TOKEN not set – skipping social scheduling")
        return []

    profile_ids = await _get_profile_ids()
    if not profile_ids:
        logger.warning("No Buffer profile IDs found – skipping scheduling")
        return []

    tasks = []
    for video, script in zip(videos, scripts):
        vid_id = video.get("video_id")
        filepath = video.get("filepath", "")
        for platform, profile_id in profile_ids.items():
            tasks.append(
                _schedule_post(vid_id, filepath, script, platform, profile_id)
            )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    scheduled: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, Exception):
            logger.error("Scheduling error: %s", result)
        elif result:
            scheduled.append(result)

    logger.info(
        "Buffer scheduling complete: %d/%d posts scheduled",
        len(scheduled),
        len(tasks),
    )
    return scheduled
