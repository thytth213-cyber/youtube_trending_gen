#!/usr/bin/env python3
"""
health_check.py – Lightweight health-check script.

Returns exit code 0 if the system is healthy, non-zero otherwise.
Can be called by Docker HEALTHCHECK or an external monitoring tool.
"""

import sys
import os

# Allow running from any directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_database() -> bool:
    try:
        from src.database import get_session, Video
        with get_session() as session:
            session.query(Video).limit(1).all()
        return True
    except Exception as exc:
        print(f"[FAIL] Database check: {exc}", file=sys.stderr)
        return False


def check_data_dirs() -> bool:
    import config
    for d in (config.DATA_DIR, config.LOGS_DIR, config.VIDEOS_DIR, config.THUMBNAILS_DIR):
        if not d.exists():
            print(f"[FAIL] Missing directory: {d}", file=sys.stderr)
            return False
    return True


def main() -> int:
    print("[INFO] Running health checks…")
    checks = {
        "database": check_database,
        "data_dirs": check_data_dirs,
    }
    all_ok = True
    for name, fn in checks.items():
        result = fn()
        status = "OK" if result else "FAIL"
        print(f"[{status}] {name}")
        if not result:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
