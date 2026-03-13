"""
Structured logging setup for the AI Content Automation System.

Features:
- Console + rotating file handler
- Daily log rotation, keep 30 days
- Configurable log level via LOG_LEVEL env var
"""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import config

# Formatter used by all handlers
_FORMATTER = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

_configured = False


def _setup_root_logger() -> None:
    global _configured  # noqa: PLW0603
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    # Console handler (always present)
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setFormatter(_FORMATTER)
    root.addHandler(_ch)

    # File handler (rotating, daily, keep 30 days)
    log_file: Path = config.LOG_FILE
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _fh = TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
            utc=True,
        )
        _fh.setFormatter(_FORMATTER)
        root.addHandler(_fh)
    except (OSError, PermissionError) as exc:
        root.warning("Could not create file log handler: %s", exc)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger; initialises root logger on first call."""
    _setup_root_logger()
    return logging.getLogger(name)
