# Docker Setup Guide

## Prerequisites

- Docker Engine 24+
- Docker Compose v2+
- At least 2 GB free disk space

---

## 1. Initial Setup

```bash
# Clone the repo
git clone https://github.com/thytth213-cyber/youtube_trending_gen.git
cd youtube_trending_gen

# Copy environment template and fill in your credentials
cp .env.example .env
nano .env  # or use your editor of choice

# Create data directories (Docker mounts these as volumes)
mkdir -p data/videos data/thumbnails logs
```

---

## 2. Build & Start

```bash
# Build the Docker image
docker compose build

# Start in detached mode
docker compose up -d

# Follow logs
docker compose logs -f content-ai
```

---

## 3. Environment Variables

All credentials are stored in `.env` (never committed to git).
The file is mounted **read-only** into the container at `/app/.env`.

Critical variables:

```dotenv
OPENAI_API_KEY=sk-...
YOUTUBE_API_KEY=AIza...
GOOGLE_VEO3_API_KEY=AIza...
CANVA_API_TOKEN=...
BUFFER_API_TOKEN=...
SENDGRID_API_KEY=SG....
EMAIL_RECIPIENT=you@example.com
```

---

## 4. Volumes & Persistence

| Host path | Container path | Purpose |
|---|---|---|
| `./data` | `/app/data` | SQLite DB, JSON caches, MP4 videos, PNG thumbnails |
| `./logs` | `/app/logs` | Rotating log files (30 days) |
| `./.env` | `/app/.env` (ro) | Environment variables |

The SQLite database is located at `/app/data/content_ai.db` inside the
container (or `./data/content_ai.db` on the host).

---

## 5. Resource Limits

Configured in `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      cpus: "1.0"
      memory: 1G
```

Adjust these values in `docker-compose.yml` to match your server capacity.

---

## 6. Manual Pipeline Run

To trigger the full daily pipeline immediately (without waiting for the
scheduled time):

```bash
docker exec content-ai python scripts/manual_run.py
```

---

## 7. Health Check

```bash
docker exec content-ai python scripts/health_check.py
```

---

## 8. Database Backup

```bash
docker exec content-ai bash scripts/backup_database.sh
```

Backups are saved to `./data/content_ai_backup.db` (latest) and
`./data/content_ai_backup_YYYYMMDD_HHMMSS.db` (timestamped, last 7 kept).

---

## 9. Stopping & Cleaning Up

```bash
# Stop the container (data is preserved in volumes)
docker compose down

# Remove volumes too (DELETES ALL DATA)
docker compose down -v
```

---

## 10. Updating the Application

```bash
git pull
docker compose build --no-cache
docker compose up -d
```

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| Container exits immediately | Check logs: `docker compose logs content-ai` |
| "Missing env var" warning | Ensure `.env` is present and readable |
| DB not found | Check `./data/` directory permissions |
| Videos not generating | Verify `GOOGLE_VEO3_API_KEY` in `.env` |
| No emails received | Verify `SENDGRID_API_KEY` and `EMAIL_RECIPIENT` |
