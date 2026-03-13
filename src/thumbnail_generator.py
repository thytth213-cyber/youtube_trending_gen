"""
Thumbnail Generation Module

Uses the Canva API to auto-generate YouTube thumbnails (1280×720 px PNG)
matching each video's content. Falls back to a plain-colour placeholder
when the Canva API is unavailable.

Output
------
PNG files in ``/app/data/thumbnails/``
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from src.database import Thumbnail, get_session, log_api_call
from src.logger import get_logger
from src.utils import async_retry

logger = get_logger(__name__)

# Canva API endpoint for design creation
_CANVA_API_BASE = "https://api.canva.com/rest/v1"
_THUMBNAIL_WIDTH = 1280
_THUMBNAIL_HEIGHT = 720


# ---------------------------------------------------------------------------
# Fallback: local Pillow-based placeholder
# ---------------------------------------------------------------------------


def _generate_placeholder(title: str, filepath: Path) -> None:
    """
    Create a minimal 1280×720 placeholder thumbnail using Pillow.
    This is the fallback when the Canva API is unavailable.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore

        img = Image.new("RGB", (_THUMBNAIL_WIDTH, _THUMBNAIL_HEIGHT), color=(20, 20, 40))
        draw = ImageDraw.Draw(img)

        # Draw a gradient-like border
        for i in range(10):
            draw.rectangle(
                [i, i, _THUMBNAIL_WIDTH - i, _THUMBNAIL_HEIGHT - i],
                outline=(60 + i * 10, 80 + i * 5, 180 - i * 5),
            )

        # Title text (wrap at 40 chars)
        lines = []
        words = title.split()
        line = ""
        for word in words:
            if len(line) + len(word) + 1 <= 40:
                line = f"{line} {word}".strip()
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 64)
        except (IOError, OSError):
            font = ImageFont.load_default()

        y_start = (_THUMBNAIL_HEIGHT - len(lines) * 80) // 2
        for i, text_line in enumerate(lines[:3]):
            draw.text((80, y_start + i * 80), text_line, font=font, fill=(255, 255, 255))

        img.save(str(filepath), "PNG")
        logger.debug("Placeholder thumbnail saved: %s", filepath)
    except ImportError:
        logger.warning("Pillow not available – creating empty thumbnail file")
        filepath.write_bytes(b"")


# ---------------------------------------------------------------------------
# Canva API thumbnail generation
# ---------------------------------------------------------------------------


@async_retry(max_attempts=3, initial_delay=2.0, exceptions=(Exception,))
async def _generate_canva_thumbnail(
    script: dict[str, Any],
    filepath: Path,
) -> bool:
    """
    Call the Canva API to generate a thumbnail.  Returns True on success.
    """
    import httpx  # type: ignore

    headers = {
        "Authorization": f"Bearer {config.CANVA_API_TOKEN}",
        "Content-Type": "application/json",
    }

    # 1. Create a design from a template
    payload = {
        "asset_type": "IMAGE",
        "title": script.get("title", "Thumbnail"),
        "design_type": {"type": "custom", "width": _THUMBNAIL_WIDTH, "height": _THUMBNAIL_HEIGHT},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_CANVA_API_BASE}/designs",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        design_data = resp.json()
        design_id = design_data.get("design", {}).get("id")

        if not design_id:
            raise ValueError("Canva: no design_id in response")

        # 2. Export the design as PNG
        export_resp = await client.post(
            f"{_CANVA_API_BASE}/exports",
            headers=headers,
            json={"design_id": design_id, "format": "png"},
        )
        export_resp.raise_for_status()
        export_data = export_resp.json()
        download_url = (
            export_data.get("job", {}).get("urls", [None])[0]
        )

        if not download_url:
            raise ValueError("Canva: no download URL in export response")

        # 3. Download the PNG
        img_resp = await client.get(download_url)
        img_resp.raise_for_status()
        filepath.write_bytes(img_resp.content)

    log_api_call(
        service="canva",
        endpoint="designs+exports",
        cost=0.0,  # Canva Pro – subscription cost, not per-call
        success=True,
        notes=f"design_id={design_id}",
    )
    logger.info("Canva thumbnail generated: %s", filepath.name)
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_thumbnail(
    script: dict[str, Any],
    video_id: int,
) -> str | None:
    """
    Generate a thumbnail for one video.  Returns the saved filepath or None.
    """
    safe_title = "".join(
        c if c.isalnum() or c in " _-" else "_"
        for c in script.get("title", "thumb")
    )[:50]
    filename = f"thumb_{video_id}_{safe_title}.png"
    filepath = config.THUMBNAILS_DIR / filename

    success = False
    if config.CANVA_API_TOKEN:
        try:
            success = await _generate_canva_thumbnail(script, filepath)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Canva thumbnail failed for video id=%d: %s – using fallback",
                video_id,
                exc,
            )

    if not success:
        await asyncio.get_event_loop().run_in_executor(
            None, _generate_placeholder, script.get("title", "Video"), filepath
        )

    # Record in database
    with get_session() as session:
        thumb = Thumbnail(video_id=video_id, filepath=str(filepath))
        session.add(thumb)
        session.commit()

    return str(filepath)


async def generate_thumbnails(
    scripts_with_ids: list[tuple[dict[str, Any], int]],
) -> list[str]:
    """
    Generate thumbnails for all ``(script, video_id)`` pairs in parallel.

    Returns a list of file paths for successfully generated thumbnails.
    """
    logger.info("Generating %d thumbnails…", len(scripts_with_ids))
    tasks = [
        generate_thumbnail(script, vid_id)
        for script, vid_id in scripts_with_ids
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    paths: list[str] = []
    for result in results:
        if isinstance(result, Exception):
            logger.error("Thumbnail generation error: %s", result)
        elif result:
            paths.append(result)

    logger.info("Thumbnails generated: %d/%d", len(paths), len(scripts_with_ids))
    return paths
