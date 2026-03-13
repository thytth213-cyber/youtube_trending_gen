"""
Video Generation Module

Submits scripts to the Google Veo 3 API (via google-generativeai),
polls for completion, downloads the resulting MP4 files, and tracks cost.

Output
------
- MP4 files in ``/app/data/videos/``
- Database records updated with status, filepath, cost, and duration
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from src.database import log_api_call, update_video_status
from src.logger import get_logger
from src.utils import async_retry

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VEO3_MODEL = "veo-003"
VIDEO_POLL_INTERVAL = 30  # seconds between status checks
VIDEO_POLL_MAX_WAIT = 600  # 10 minutes maximum wait per video
VIDEO_RESOLUTION = "1080p"
VIDEO_ASPECT_RATIO = "9:16"  # vertical for social media


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_veo_prompt(script: dict[str, Any]) -> str:
    """
    Convert a content script dict into a detailed cinematic Veo 3 prompt.
    """
    title = script.get("title", "Untitled")
    hook = script.get("hook", "")
    body = script.get("script", "")[:300]  # keep prompt concise
    thumbnail_desc = script.get("thumbnail_description", "")
    content_type = script.get("content_type", "educational")

    style_map = {
        "educational": "clean, modern studio look with infographic overlays",
        "entertainment": "dynamic, high-energy with vibrant colors and fast cuts",
        "motivational": "cinematic, inspirational with warm golden-hour lighting",
    }
    style = style_map.get(content_type, style_map["educational"])

    return (
        f"Create a vertical 9:16 social media video for: '{title}'. "
        f"Style: {style}. "
        f"Opening: {hook} "
        f"Content: {body} "
        f"Visual direction: {thumbnail_desc} "
        f"Resolution: {VIDEO_RESOLUTION}, format: MP4, duration: 45-60 seconds. "
        f"Cinematic quality, professional production value, subtitles ready."
    )


# ---------------------------------------------------------------------------
# Single video generation
# ---------------------------------------------------------------------------


@async_retry(max_attempts=2, initial_delay=5.0, exceptions=(Exception,))
async def _generate_single_video(
    script: dict[str, Any],
    video_id: int,
) -> dict[str, Any] | None:
    """
    Submit a script to Veo 3, poll until complete, and download the video.

    Returns a dict with ``filepath``, ``duration``, and ``cost`` or ``None``
    on failure.
    """
    if not config.GOOGLE_VEO3_API_KEY:
        logger.warning("GOOGLE_VEO3_API_KEY not set – skipping video generation")
        return None

    try:
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=config.GOOGLE_VEO3_API_KEY)
        model = genai.GenerativeModel(VEO3_MODEL)

        prompt = _build_veo_prompt(script)
        logger.info(
            "Submitting video id=%d to Veo 3: %s…", video_id, prompt[:60]
        )

        # Submit generation request
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: model.generate_content(
                prompt,
                generation_config={
                    "response_mime_type": "video/mp4",
                },
            ),
        )

        veo3_id = getattr(response, "operation_name", f"local_{video_id}")
        update_video_status(video_id, "processing", veo3_id=veo3_id)

        # Poll for completion
        start = time.time()
        while time.time() - start < VIDEO_POLL_MAX_WAIT:
            if hasattr(response, "done") and not response.done():
                await asyncio.sleep(VIDEO_POLL_INTERVAL)
                response = await asyncio.get_event_loop().run_in_executor(
                    None, response.refresh
                )
            else:
                break

        # Download the video bytes
        video_bytes: bytes | None = None
        if hasattr(response, "parts"):
            for part in response.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    video_bytes = part.inline_data.data
                    break

        if not video_bytes:
            logger.error("Video id=%d: no video data in response", video_id)
            return None

        # Save to disk
        safe_title = "".join(
            c if c.isalnum() or c in " _-" else "_"
            for c in script.get("title", "video")
        )[:50]
        filename = f"video_{video_id}_{safe_title}.mp4"
        filepath = config.VIDEOS_DIR / filename

        with open(filepath, "wb") as fh:
            fh.write(video_bytes)

        file_size = len(video_bytes)
        # Estimate duration from file size (~500KB/s for compressed 1080p)
        duration = round(file_size / 500_000, 1)
        cost = round(duration * config.VEO3_COST_PER_SECOND, 4)

        log_api_call(
            service="veo3",
            endpoint="generate_content",
            cost=cost,
            success=True,
            notes=f"video_id={video_id} duration={duration}s",
        )

        return {"filepath": str(filepath), "duration": duration, "cost": cost}

    except Exception as exc:  # noqa: BLE001
        logger.error("Veo 3 generation failed for video id=%d: %s", video_id, exc)
        log_api_call(
            service="veo3",
            endpoint="generate_content",
            cost=0.0,
            success=False,
            notes=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# Batch generation (parallel)
# ---------------------------------------------------------------------------


async def generate_videos(
    scripts_with_ids: list[tuple[dict[str, Any], int]],
) -> list[dict[str, Any]]:
    """
    Generate videos for all ``(script, video_id)`` pairs in parallel.

    Parameters
    ----------
    scripts_with_ids:
        List of ``(script_dict, database_video_id)`` tuples.

    Returns
    -------
    list[dict]
        List of result dicts with ``video_id``, ``filepath``, ``duration``,
        and ``cost`` for each successfully generated video.
    """
    logger.info("Starting parallel video generation for %d scripts…", len(scripts_with_ids))

    tasks = [
        _generate_single_video(script, vid_id)
        for script, vid_id in scripts_with_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    completed: list[dict[str, Any]] = []
    for (script, vid_id), result in zip(scripts_with_ids, results):
        if isinstance(result, Exception) or result is None:
            update_video_status(vid_id, "failed")
            logger.error("Video id=%d failed", vid_id)
        else:
            update_video_status(
                vid_id,
                "completed",
                filepath=result["filepath"],
                cost=result["cost"],
                duration=result["duration"],
            )
            completed.append({"video_id": vid_id, **result})
            logger.info(
                "Video id=%d completed: %s (%.1fs, $%.4f)",
                vid_id,
                result["filepath"],
                result["duration"],
                result["cost"],
            )

    logger.info(
        "Video generation complete: %d/%d succeeded",
        len(completed),
        len(scripts_with_ids),
    )
    return completed
