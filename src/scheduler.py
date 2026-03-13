"""
Scheduler Module

Uses APScheduler to run the full daily automation pipeline:

  00:00 UTC  Fetch trending topics
  00:15 UTC  Generate 10 video scripts (ChatGPT)
  00:30 UTC  Submit scripts to Veo 3 for parallel video generation
  02:00 UTC  Generate thumbnails (Canva)
  02:30 UTC  Prepare social media metadata
  03:00 UTC  Send all content to Buffer for scheduling
  03:30 UTC  Generate completion report + send email
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore

import config
from src.analytics import run_daily_report
from src.buffer_integration import schedule_posts
from src.content_generator import generate_scripts
from src.database import create_video, init_db
from src.logger import get_logger
from src.thumbnail_generator import generate_thumbnails
from src.trends import fetch_trends
from src.video_generator import generate_videos

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None


# ---------------------------------------------------------------------------
# Individual job functions (each runs in a background thread)
# ---------------------------------------------------------------------------


def _run_async(coro: Any) -> Any:
    """Run *coro* in a new event loop (safe for APScheduler threads)."""
    return asyncio.run(coro)


# -- Step 1: Trends ----------------------------------------------------------

def job_fetch_trends() -> None:
    logger.info("=== JOB: Fetch Trends ===")
    try:
        topics = _run_async(fetch_trends(force=True))
        logger.info("Trends fetched: %d topics", len(topics))
    except Exception as exc:  # noqa: BLE001
        logger.error("job_fetch_trends failed: %s", exc)


# -- Step 2: Generate scripts ------------------------------------------------

def job_generate_scripts() -> None:
    logger.info("=== JOB: Generate Scripts ===")
    try:
        from src.utils import load_json

        cached = load_json(config.TRENDS_FILE, {})
        topics = cached.get("topics", [])
        if not topics:
            logger.warning("No trends available – fetching now")
            topics = _run_async(fetch_trends())

        scripts = _run_async(generate_scripts(topics[: config.VIDEOS_PER_DAY]))
        logger.info("Scripts generated: %d", len(scripts))
    except Exception as exc:  # noqa: BLE001
        logger.error("job_generate_scripts failed: %s", exc)


# -- Step 3: Generate videos -------------------------------------------------

def job_generate_videos() -> None:
    logger.info("=== JOB: Generate Videos ===")
    try:
        from src.utils import load_json

        cached = load_json(config.SCRIPTS_FILE, {})
        scripts = cached.get("scripts", [])
        if not scripts:
            logger.warning("No scripts found – skipping video generation")
            return

        # Persist scripts to DB and collect (script, video_id) pairs
        pairs: list[tuple[dict, int]] = []
        for script in scripts:
            db_video = create_video(
                title=script.get("title", "Untitled"),
                script=script.get("script", ""),
                hashtags=", ".join(script.get("hashtags", [])),
                seo_keywords=", ".join(script.get("seo_keywords", [])),
                content_type=script.get("content_type", "educational"),
            )
            pairs.append((script, db_video.id))

        completed = _run_async(generate_videos(pairs))
        logger.info("Videos generated: %d", len(completed))
    except Exception as exc:  # noqa: BLE001
        logger.error("job_generate_videos failed: %s", exc)


# -- Step 4: Generate thumbnails ---------------------------------------------

def job_generate_thumbnails() -> None:
    logger.info("=== JOB: Generate Thumbnails ===")
    try:
        from src.database import Video

        from src.utils import load_json

        cached = load_json(config.SCRIPTS_FILE, {})
        scripts = cached.get("scripts", [])

        # Look up DB video IDs created today
        today = datetime.now(timezone.utc).date()
        from datetime import timedelta

        from src.database import get_session

        start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        with get_session() as session:
            today_videos = (
                session.query(Video)
                .filter(Video.created_at >= start, Video.created_at < end)
                .order_by(Video.id)
                .all()
            )
            video_ids = [v.id for v in today_videos]

        pairs = list(zip(scripts[: len(video_ids)], video_ids))
        paths = _run_async(generate_thumbnails(pairs))
        logger.info("Thumbnails generated: %d", len(paths))
    except Exception as exc:  # noqa: BLE001
        logger.error("job_generate_thumbnails failed: %s", exc)


# -- Step 5: Schedule on Buffer ----------------------------------------------

def job_schedule_buffer() -> None:
    logger.info("=== JOB: Schedule Buffer Posts ===")
    try:
        from datetime import timedelta

        from src.database import Video, get_session
        from src.utils import load_json

        cached = load_json(config.SCRIPTS_FILE, {})
        scripts = cached.get("scripts", [])

        today = datetime.now(timezone.utc).date()
        start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        with get_session() as session:
            today_videos = (
                session.query(Video)
                .filter(
                    Video.created_at >= start,
                    Video.created_at < end,
                    Video.status == "completed",
                )
                .order_by(Video.id)
                .all()
            )
            video_data = [
                {"video_id": v.id, "filepath": v.filepath or ""}
                for v in today_videos
            ]

        posted = _run_async(
            schedule_posts(video_data, scripts[: len(video_data)])
        )
        logger.info("Buffer posts scheduled: %d", len(posted))
    except Exception as exc:  # noqa: BLE001
        logger.error("job_schedule_buffer failed: %s", exc)


# -- Step 6: Daily report ----------------------------------------------------

def job_daily_report() -> None:
    logger.info("=== JOB: Daily Report ===")
    try:
        from src.database import backup_db

        backup_db()
        run_daily_report()
    except Exception as exc:  # noqa: BLE001
        logger.error("job_daily_report failed: %s", exc)


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def _parse_run_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute)."""
    try:
        h, m = time_str.split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        return 0, 0


def start_scheduler() -> BackgroundScheduler:
    """Create, configure, and start the APScheduler instance."""
    global _scheduler  # noqa: PLW0603

    init_db()

    base_h, base_m = _parse_run_time(config.DAILY_RUN_TIME)
    tz = config.USER_TIMEZONE

    scheduler = BackgroundScheduler(timezone=tz)

    def _at(h: int, m: int) -> CronTrigger:
        return CronTrigger(hour=h, minute=m, timezone=tz)

    # Register jobs at offsets relative to DAILY_RUN_TIME
    def _offset(minutes: int) -> tuple[int, int]:
        total = base_h * 60 + base_m + minutes
        return (total // 60) % 24, total % 60

    scheduler.add_job(job_fetch_trends,       _at(*_offset(0)),   id="fetch_trends",       replace_existing=True)
    scheduler.add_job(job_generate_scripts,   _at(*_offset(15)),  id="gen_scripts",        replace_existing=True)
    scheduler.add_job(job_generate_videos,    _at(*_offset(30)),  id="gen_videos",         replace_existing=True)
    scheduler.add_job(job_generate_thumbnails,_at(*_offset(120)), id="gen_thumbnails",     replace_existing=True)
    scheduler.add_job(job_schedule_buffer,    _at(*_offset(180)), id="schedule_buffer",    replace_existing=True)
    scheduler.add_job(job_daily_report,       _at(*_offset(210)), id="daily_report",       replace_existing=True)

    scheduler.start()
    _scheduler = scheduler
    logger.info("Scheduler started. Jobs: %s", [j.id for j in scheduler.get_jobs()])
    return scheduler


def stop_scheduler() -> None:
    """Gracefully stop the scheduler."""
    global _scheduler  # noqa: PLW0603
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
        _scheduler = None


def run_full_pipeline_now() -> None:
    """
    Manually trigger the entire daily pipeline sequentially.
    Useful for ``scripts/manual_run.py``.
    """
    logger.info("=== Manual full pipeline run ===")
    for job_fn in [
        job_fetch_trends,
        job_generate_scripts,
        job_generate_videos,
        job_generate_thumbnails,
        job_schedule_buffer,
        job_daily_report,
    ]:
        job_fn()
    logger.info("=== Manual pipeline run complete ===")
