# ─────────────────────────────────────────────────────────────────────────────
# AI Content Automation System – Dockerfile
# Base: python:3.11-slim
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Metadata
LABEL maintainer="Content AI" \
      description="Automated AI content creation pipeline"

# ── Environment ──────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        curl \
        ca-certificates \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
COPY config.py main.py ./
COPY src/ ./src/

# ── Persistent data directories ───────────────────────────────────────────────
RUN mkdir -p /app/data/videos /app/data/thumbnails /app/logs

# ── Health-check (lightweight – just checks that Python is alive) ─────────────
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# ── Default command ───────────────────────────────────────────────────────────
CMD ["python", "main.py"]
