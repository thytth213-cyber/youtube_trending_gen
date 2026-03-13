"""
Trend Research Module

Sources
-------
1. YouTube Data API v3  – trending videos by category / region
2. Reddit PRAW          – hot posts across configurable subreddits
3. Google Trends        – pytrends rising queries

Output
------
Writes ``data/trends.json`` and returns a list of topic dicts:

.. code-block:: json

    [
      {
        "title": "...",
        "source": "youtube|reddit|google_trends",
        "keywords": ["kw1", "kw2"],
        "view_count": 1234567,
        "engagement": 0.05,
        "score": 9.8
      }
    ]
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import config
from src.logger import get_logger
from src.utils import async_retry, save_json, load_json

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_TTL_SECONDS = 60 * 60 * 22  # ~22 hours – avoid redundant calls

TRENDING_SUBREDDITS = [
    "technology",
    "science",
    "worldnews",
    "business",
    "entertainment",
    "gaming",
    "sports",
    "todayilearned",
]

YOUTUBE_REGION = "US"
YOUTUBE_MAX_RESULTS = 20
GOOGLE_TRENDS_KWS = ["AI", "technology", "viral", "trending", "news"]


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _is_cache_valid() -> bool:
    cached = load_json(config.TRENDS_FILE)
    if not cached:
        return False
    ts = cached.get("fetched_at", 0)
    return (time.time() - ts) < CACHE_TTL_SECONDS


# ---------------------------------------------------------------------------
# YouTube trending
# ---------------------------------------------------------------------------


@async_retry(max_attempts=3, initial_delay=2.0)
async def _fetch_youtube_trending() -> list[dict[str, Any]]:
    if not config.YOUTUBE_API_KEY:
        logger.warning("YOUTUBE_API_KEY not set – skipping YouTube trending")
        return []

    from googleapiclient.discovery import build  # type: ignore

    def _sync() -> list[dict[str, Any]]:
        service = build("youtube", "v3", developerKey=config.YOUTUBE_API_KEY)
        resp = (
            service.videos()
            .list(
                part="snippet,statistics",
                chart="mostPopular",
                regionCode=YOUTUBE_REGION,
                maxResults=YOUTUBE_MAX_RESULTS,
            )
            .execute()
        )
        results = []
        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            view_count = int(stats.get("viewCount", 0))
            like_count = int(stats.get("likeCount", 0))
            engagement = round(like_count / max(view_count, 1), 4)
            title = snippet.get("title", "")
            tags = snippet.get("tags", [])
            results.append(
                {
                    "title": title,
                    "source": "youtube",
                    "keywords": tags[:10],
                    "view_count": view_count,
                    "engagement": engagement,
                    "score": round(view_count / 1_000_000 * 10, 2),
                }
            )
        logger.info("YouTube trending: %d items fetched", len(results))
        return results

    return await asyncio.get_event_loop().run_in_executor(None, _sync)


# ---------------------------------------------------------------------------
# Reddit trending
# ---------------------------------------------------------------------------


@async_retry(max_attempts=3, initial_delay=2.0)
async def _fetch_reddit_trending() -> list[dict[str, Any]]:
    if not config.REDDIT_CLIENT_ID or not config.REDDIT_CLIENT_SECRET:
        logger.warning("Reddit credentials not set – skipping Reddit trending")
        return []

    import praw  # type: ignore

    def _sync() -> list[dict[str, Any]]:
        reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            user_agent=config.REDDIT_USER_AGENT,
        )
        results = []
        for sub_name in TRENDING_SUBREDDITS:
            try:
                subreddit = reddit.subreddit(sub_name)
                for post in subreddit.hot(limit=3):
                    score = post.score
                    results.append(
                        {
                            "title": post.title,
                            "source": "reddit",
                            "keywords": [sub_name] + post.title.lower().split()[:5],
                            "view_count": score,
                            "engagement": round(post.upvote_ratio, 4),
                            "score": round(score / 10_000, 2),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Reddit r/%s failed: %s", sub_name, exc)
        logger.info("Reddit trending: %d items fetched", len(results))
        return results

    return await asyncio.get_event_loop().run_in_executor(None, _sync)


# ---------------------------------------------------------------------------
# Google Trends
# ---------------------------------------------------------------------------


@async_retry(max_attempts=3, initial_delay=2.0)
async def _fetch_google_trends() -> list[dict[str, Any]]:
    def _sync() -> list[dict[str, Any]]:
        try:
            from pytrends.request import TrendReq  # type: ignore

            pytrends = TrendReq(hl="en-US", tz=0)
            trending_df = pytrends.trending_searches(pn="united_states")
            results = []
            for title in trending_df[0].tolist()[:20]:
                results.append(
                    {
                        "title": str(title),
                        "source": "google_trends",
                        "keywords": str(title).lower().split()[:5],
                        "view_count": 0,
                        "engagement": 0.0,
                        "score": 5.0,  # generic score for trending searches
                    }
                )
            logger.info("Google Trends: %d items fetched", len(results))
            return results
        except Exception as exc:  # noqa: BLE001
            logger.warning("Google Trends fetch failed: %s", exc)
            return []

    return await asyncio.get_event_loop().run_in_executor(None, _sync)


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


async def fetch_trends(force: bool = False) -> list[dict[str, Any]]:
    """
    Fetch, merge, deduplicate, and rank trending topics from all sources.

    Parameters
    ----------
    force:
        Bypass the cache and always fetch fresh data.

    Returns
    -------
    list[dict]
        Top-10 trending topics, sorted by score descending.
    """
    if not force and _is_cache_valid():
        cached = load_json(config.TRENDS_FILE, {})
        topics = cached.get("topics", [])
        logger.info("Returning %d cached trending topics", len(topics))
        return topics

    logger.info("Fetching fresh trending data from all sources…")
    yt, reddit, gt = await asyncio.gather(
        _fetch_youtube_trending(),
        _fetch_reddit_trending(),
        _fetch_google_trends(),
    )

    all_topics: list[dict[str, Any]] = yt + reddit + gt

    # Deduplicate by lowercased title
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for topic in all_topics:
        key = topic["title"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(topic)

    # Sort by score descending, take top 10
    top = sorted(unique, key=lambda t: t["score"], reverse=True)[:10]

    payload = {
        "fetched_at": time.time(),
        "fetched_at_iso": datetime.now(timezone.utc).isoformat(),
        "topics": top,
    }
    save_json(payload, config.TRENDS_FILE)
    logger.info("Trending data saved: %d topics", len(top))
    return top
