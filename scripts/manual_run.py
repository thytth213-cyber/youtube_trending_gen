#!/usr/bin/env python3
"""
manual_run.py – Trigger the full daily pipeline immediately.

Usage:
    docker exec content-ai python scripts/manual_run.py
    # or locally:
    python scripts/manual_run.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import init_db
from src.logger import get_logger
from src.scheduler import run_full_pipeline_now

logger = get_logger("manual_run")


def main() -> None:
    logger.info("Manual pipeline run initiated")
    init_db()
    run_full_pipeline_now()
    logger.info("Manual pipeline run complete")


if __name__ == "__main__":
    main()
