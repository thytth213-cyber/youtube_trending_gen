"""
Shared utility functions: retry logic, JSON helpers, HTTP helpers.
"""

import asyncio
import functools
import json
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from src.logger import get_logger

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Retry with exponential back-off
# ---------------------------------------------------------------------------

def retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Decorator that retries *func* up to *max_attempts* times on *exceptions*.
    Delay starts at *initial_delay* seconds and is multiplied by *backoff*
    after each failure.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        logger.warning(
                            "%s – attempt %d/%d failed: %s. Retrying in %.1fs…",
                            func.__qualname__,
                            attempt,
                            max_attempts,
                            exc,
                            delay,
                        )
                        time.sleep(delay)
                        delay *= backoff
                    else:
                        logger.error(
                            "%s – all %d attempts failed: %s",
                            func.__qualname__,
                            max_attempts,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


def async_retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Async version of :func:`retry`.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        logger.warning(
                            "%s – attempt %d/%d failed: %s. Retrying in %.1fs…",
                            func.__qualname__,
                            attempt,
                            max_attempts,
                            exc,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        delay *= backoff
                    else:
                        logger.error(
                            "%s – all %d attempts failed: %s",
                            func.__qualname__,
                            max_attempts,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def save_json(data: Any, path: Path) -> None:
    """Write *data* as pretty-printed JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
    logger.debug("Saved JSON → %s", path)


def load_json(path: Path, default: Any = None) -> Any:
    """Load JSON from *path*; return *default* if missing or invalid."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.debug("Could not load %s: %s", path, exc)
        return default


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def truncate(text: str, max_len: int = 80) -> str:
    """Return *text* truncated to *max_len* characters."""
    return text if len(text) <= max_len else text[: max_len - 3] + "…"
