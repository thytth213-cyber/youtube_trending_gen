"""
Centralized configuration management for the AI Content Automation System.
Loads environment variables from .env and provides validated settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env file (only when it exists – Docker mounts it at /app/.env)
# ---------------------------------------------------------------------------
_env_path = Path("/app/.env") if Path("/app/.env").exists() else Path(".env")
load_dotenv(dotenv_path=_env_path, override=False)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _require(key: str) -> str:
    """Return the value of *key* or raise if it is missing/empty."""
    value = os.getenv(key, "").strip()
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is missing or empty. "
            "Check your .env file."
        )
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

YOUTUBE_API_KEY: str = _optional("YOUTUBE_API_KEY")
OPENAI_API_KEY: str = _optional("OPENAI_API_KEY")
OPENAI_MODEL: str = _optional("OPENAI_MODEL", "gpt-4o")
GOOGLE_VEO3_API_KEY: str = _optional("GOOGLE_VEO3_API_KEY")
CANVA_API_TOKEN: str = _optional("CANVA_API_TOKEN")
BUFFER_API_TOKEN: str = _optional("BUFFER_API_TOKEN")
SENDGRID_API_KEY: str = _optional("SENDGRID_API_KEY")
REDDIT_CLIENT_ID: str = _optional("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET: str = _optional("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT: str = _optional("REDDIT_USER_AGENT", "ContentAI/1.0")

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

EMAIL_RECIPIENT: str = _optional("EMAIL_RECIPIENT")
EMAIL_SENDER: str = _optional("EMAIL_SENDER", "noreply@contentai.local")

# ---------------------------------------------------------------------------
# Scheduling & Timezone
# ---------------------------------------------------------------------------

USER_TIMEZONE: str = _optional("USER_TIMEZONE", "UTC")
DAILY_RUN_TIME: str = _optional("DAILY_RUN_TIME", "00:00")

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

APP_ENV: str = _optional("APP_ENV", "prod")
LOG_LEVEL: str = _optional("LOG_LEVEL", "INFO").upper()
VIDEOS_PER_DAY: int = int(_optional("VIDEOS_PER_DAY", "10"))

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

DATABASE_URL: str = _optional(
    "DATABASE_URL", "sqlite:////app/data/content_ai.db"
)

# ---------------------------------------------------------------------------
# Paths (resolved inside or outside of Docker)
# ---------------------------------------------------------------------------

_BASE_DIR = Path("/app") if Path("/app").exists() else Path(__file__).parent

DATA_DIR: Path = _BASE_DIR / "data"
LOGS_DIR: Path = _BASE_DIR / "logs"
VIDEOS_DIR: Path = DATA_DIR / "videos"
THUMBNAILS_DIR: Path = DATA_DIR / "thumbnails"
TRENDS_FILE: Path = DATA_DIR / "trends.json"
SCRIPTS_FILE: Path = DATA_DIR / "scripts.json"
DB_BACKUP_FILE: Path = DATA_DIR / "content_ai_backup.db"
LOG_FILE: Path = LOGS_DIR / "app.log"

# Ensure directories exist (gracefully handle read-only envs)
for _d in (DATA_DIR, LOGS_DIR, VIDEOS_DIR, THUMBNAILS_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

VEO3_COST_PER_SECOND: float = float(_optional("VEO3_COST_PER_SECOND", "0.15"))

# ---------------------------------------------------------------------------
# Validation helper (called from main.py on startup)
# ---------------------------------------------------------------------------

REQUIRED_KEYS = [
    "OPENAI_API_KEY",
    "YOUTUBE_API_KEY",
    "SENDGRID_API_KEY",
    "EMAIL_RECIPIENT",
]


def validate_config() -> list[str]:
    """
    Return a list of missing required environment variable names.
    An empty list means the configuration is valid.
    """
    missing = []
    for key in REQUIRED_KEYS:
        if not os.getenv(key, "").strip():
            missing.append(key)
    return missing
