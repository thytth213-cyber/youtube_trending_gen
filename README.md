# YouTube Trending Gen – AI Content Automation System

> **Automated AI pipeline** that creates 10 social-media-ready videos per day (~300/month) using trending topic research, ChatGPT script generation, Google Veo 3 video synthesis, Canva thumbnail design, and Buffer multi-platform scheduling.

---

## ✨ Features

| Module | Description |
|---|---|
| **Trend Research** | YouTube Data API, Reddit (PRAW), Google Trends |
| **Script Generation** | OpenAI GPT-4o – 10 scripts/day, parallel async |
| **Video Generation** | Google Veo 3 (1080p, 9:16 vertical) |
| **Thumbnails** | Canva API (1280×720 PNG) with Pillow fallback |
| **Scheduling** | Buffer API – YouTube, TikTok, Instagram, Twitter/X |
| **Analytics** | Daily HTML email report via SendGrid |
| **Database** | SQLite + SQLAlchemy ORM (persisted via Docker volume) |
| **Docker** | `python:3.11-slim` + FFmpeg, auto-restart, resource limits |

---

## 🏃 Quick Start

### 1. Clone & configure

```bash
git clone https://github.com/thytth213-cyber/youtube_trending_gen.git
cd youtube_trending_gen
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start with Docker Compose

```bash
mkdir -p data/videos data/thumbnails logs
docker compose up -d
```

### 3. Check logs

```bash
docker compose logs -f
```

### 4. Trigger a manual run

```bash
docker exec content-ai python scripts/manual_run.py
```

---

## 📁 Project Structure

```
youtube_trending_gen/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── .gitignore
├── requirements.txt
├── config.py
├── main.py
├── README.md
├── DOCKER_SETUP.md
│
├── data/                    ← Docker volume mount
│   ├── content_ai.db        ← SQLite database
│   ├── trends.json
│   ├── scripts.json
│   ├── videos/              ← Generated MP4 files
│   └── thumbnails/          ← Generated PNG thumbnails
│
├── logs/                    ← Docker volume mount
│   └── app.log
│
├── src/
│   ├── __init__.py
│   ├── logger.py
│   ├── database.py
│   ├── utils.py
│   ├── trends.py
│   ├── content_generator.py
│   ├── video_generator.py
│   ├── thumbnail_generator.py
│   ├── buffer_integration.py
│   ├── scheduler.py
│   └── analytics.py
│
├── tests/
│   ├── test_database.py
│   ├── test_trends.py
│   ├── test_content_gen.py
│   ├── test_video_gen.py
│   └── test_integrations.py
│
└── scripts/
    ├── backup_database.sh
    ├── health_check.py
    └── manual_run.py
```

---

## ⚙️ Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Description |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 key |
| `OPENAI_API_KEY` | OpenAI API key (ChatGPT Plus) |
| `GOOGLE_VEO3_API_KEY` | Google AI Studio API key |
| `CANVA_API_TOKEN` | Canva Pro API token |
| `BUFFER_API_TOKEN` | Buffer API token |
| `SENDGRID_API_KEY` | SendGrid API key (email reports) |
| `EMAIL_RECIPIENT` | Recipient for daily reports |
| `VIDEOS_PER_DAY` | Number of videos to generate (default: 10) |
| `DAILY_RUN_TIME` | Pipeline start time in HH:MM UTC (default: 00:00) |

---

## 📅 Daily Schedule (UTC)

| Time | Job |
|---|---|
| 00:00 | Fetch trending topics |
| 00:15 | Generate 10 scripts (ChatGPT) |
| 00:30 | Submit to Veo 3 for video generation |
| 02:00 | Generate thumbnails (Canva) |
| 03:00 | Schedule posts on Buffer |
| 03:30 | Send daily email report |

---

## 💰 Estimated Monthly Cost

| Service | Plan | Est. Cost |
|---|---|---|
| Google Veo 3 | AI Studio (Pro) | ~$45–65/mo |
| OpenAI GPT-4o | ChatGPT Plus | ~$20/mo |
| Canva | Pro | ~$13/mo |
| Buffer | Essentials | ~$6/mo |
| SendGrid | Free tier | $0 |
| YouTube / Reddit / Google Trends | Free APIs | $0 |
| **Total** | | **~$84–104/mo** |

---

## 🧪 Running Tests

```bash
pip install -r requirements.txt pytest
pytest tests/ -v
```

---

## 🐳 Docker Details

See [DOCKER_SETUP.md](DOCKER_SETUP.md) for detailed Docker setup and configuration instructions.

---

## 📄 License

MIT
