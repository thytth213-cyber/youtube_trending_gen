"""
main.py – Entry point for the AI Content Automation System.

On startup:
1. Validates the environment configuration
2. Initialises the SQLite database
3. Starts the APScheduler
4. Blocks until interrupted (Ctrl-C or Docker SIGTERM)
"""

import signal
import sys
import time

import config
from src.database import init_db
from src.logger import get_logger
from src.scheduler import start_scheduler, stop_scheduler

logger = get_logger("main")


def _handle_signal(signum: int, _frame: object) -> None:
    logger.info("Received signal %d – shutting down…", signum)
    stop_scheduler()
    sys.exit(0)


def main() -> None:
    logger.info("=" * 60)
    logger.info("Content AI Automation System starting…")
    logger.info("Environment: %s", config.APP_ENV)
    logger.info("=" * 60)

    # Validate configuration (warn but don't abort so the container can start
    # even with partial credentials during development)
    missing = config.validate_config()
    if missing:
        logger.warning(
            "The following required environment variables are not set: %s",
            ", ".join(missing),
        )
        if config.APP_ENV == "prod":
            logger.error("Production mode requires all keys – exiting.")
            sys.exit(1)

    # Initialise database
    init_db()

    # Register OS signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Start the scheduler
    scheduler = start_scheduler()

    logger.info("Scheduler running. Press Ctrl-C to stop.")
    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down…")
        stop_scheduler()
        logger.info("Goodbye.")


if __name__ == "__main__":
    main()
