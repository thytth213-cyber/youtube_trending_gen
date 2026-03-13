"""
Analytics & Reporting Module

Tracks cost per video, API usage, and generates daily HTML email reports
sent via SendGrid.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config
from src.database import ApiLog, DailyStat, Video, get_session, upsert_daily_stats
from src.logger import get_logger

logger = get_logger(__name__)

# Revenue estimates (USD per 1000 views)
_RPM_ESTIMATES: dict[str, float] = {
    "youtube": 4.0,
    "tiktok": 0.05,
    "instagram": 1.5,
    "twitter": 0.2,
}
_AVG_VIEWS_PER_VIDEO = 10_000  # conservative estimate


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


def collect_daily_stats(day: date | None = None) -> dict[str, Any]:
    """
    Aggregate statistics for *day* (defaults to today UTC) from the database.
    Also persists the result to the ``daily_stats`` table.
    """
    if day is None:
        day = datetime.now(timezone.utc).date()

    with get_session() as session:
        # Videos for the day
        start = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)

        videos = (
            session.query(Video)
            .filter(Video.created_at >= start, Video.created_at < end)
            .all()
        )

        total_cost = sum(v.cost for v in videos)
        completed = [v for v in videos if v.status == "completed"]
        failed = [v for v in videos if v.status == "failed"]

        # API usage breakdown
        api_logs = (
            session.query(ApiLog)
            .filter(ApiLog.timestamp >= start, ApiLog.timestamp < end)
            .all()
        )
        api_usage: dict[str, dict[str, Any]] = {}
        for log in api_logs:
            svc = log.service
            if svc not in api_usage:
                api_usage[svc] = {"calls": 0, "cost": 0.0, "tokens": 0}
            api_usage[svc]["calls"] += 1
            api_usage[svc]["cost"] += log.cost
            api_usage[svc]["tokens"] += log.tokens_used or 0

        # Estimated revenue
        total_views = len(completed) * _AVG_VIEWS_PER_VIDEO
        estimated_revenue = round(
            sum(rpm * total_views / 1000 for rpm in _RPM_ESTIMATES.values()), 2
        )

        stats = {
            "date": day.isoformat(),
            "videos_total": len(videos),
            "videos_completed": len(completed),
            "videos_failed": len(failed),
            "total_cost": round(total_cost, 4),
            "estimated_revenue": estimated_revenue,
            "roi": round(
                (estimated_revenue - total_cost) / max(total_cost, 0.01) * 100, 1
            ),
            "api_usage": api_usage,
        }

    upsert_daily_stats(
        day=day,
        videos_count=len(completed),
        total_cost=stats["total_cost"],
        estimated_revenue=estimated_revenue,
        api_usage=api_usage,
    )
    return stats


def collect_rolling_stats(days: int = 7) -> list[dict[str, Any]]:
    """Return per-day stats for the last *days* calendar days."""
    with get_session() as session:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
        rows = (
            session.query(DailyStat)
            .filter(DailyStat.date >= cutoff)
            .order_by(DailyStat.date)
            .all()
        )
        return [
            {
                "date": r.date.isoformat(),
                "videos_count": r.videos_count,
                "total_cost": r.total_cost,
                "estimated_revenue": r.estimated_revenue,
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title>Content AI – Daily Report {date}</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f5f5f5; color: #333; }}
    .container {{ max-width: 700px; margin: 30px auto; background: #fff;
                  border-radius: 8px; padding: 30px; box-shadow: 0 2px 8px rgba(0,0,0,.1); }}
    h1 {{ color: #e63946; }} h2 {{ color: #457b9d; border-bottom: 1px solid #eee; padding-bottom: 6px; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
    th {{ background: #457b9d; color: #fff; padding: 8px; text-align: left; }}
    td {{ padding: 7px 8px; border-bottom: 1px solid #eee; }}
    .good {{ color: green; font-weight: bold; }}
    .bad {{ color: red; font-weight: bold; }}
    .stat {{ display: inline-block; background: #f0f4f8; border-radius: 6px;
             padding: 12px 18px; margin: 6px; text-align: center; }}
    .stat .number {{ font-size: 2em; font-weight: bold; color: #e63946; }}
    .stat .label {{ font-size: .85em; color: #666; }}
  </style>
</head>
<body>
<div class="container">
  <h1>🎬 Content AI – Daily Report</h1>
  <p><strong>Date:</strong> {date}</p>

  <div>
    <span class="stat"><div class="number">{videos_completed}</div><div class="label">Videos Generated</div></span>
    <span class="stat"><div class="number">${total_cost}</div><div class="label">Total Cost</div></span>
    <span class="stat"><div class="number">${estimated_revenue}</div><div class="label">Est. Revenue</div></span>
    <span class="stat"><div class="number">{roi}%</div><div class="label">ROI</div></span>
  </div>

  <h2>📊 API Usage</h2>
  <table>
    <tr><th>Service</th><th>Calls</th><th>Tokens</th><th>Cost</th></tr>
    {api_rows}
  </table>

  <h2>📈 7-Day Rolling Average</h2>
  <table>
    <tr><th>Date</th><th>Videos</th><th>Cost</th><th>Revenue</th></tr>
    {rolling_rows}
  </table>

  <p style="color:#999;font-size:.8em;">
    Generated by Content AI Automation System · {generated_at}
  </p>
</div>
</body>
</html>
"""


def build_html_report(stats: dict[str, Any]) -> str:
    """Render the daily HTML report from *stats*."""
    api_rows = ""
    for svc, usage in stats.get("api_usage", {}).items():
        api_rows += (
            f"<tr><td>{svc}</td><td>{usage['calls']}</td>"
            f"<td>{usage['tokens']:,}</td><td>${usage['cost']:.4f}</td></tr>"
        )

    rolling = collect_rolling_stats(7)
    rolling_rows = ""
    for r in rolling:
        rolling_rows += (
            f"<tr><td>{r['date']}</td><td>{r['videos_count']}</td>"
            f"<td>${r['total_cost']:.4f}</td><td>${r['estimated_revenue']:.2f}</td></tr>"
        )

    return _HTML_TEMPLATE.format(
        date=stats["date"],
        videos_completed=stats["videos_completed"],
        total_cost=f"{stats['total_cost']:.4f}",
        estimated_revenue=f"{stats['estimated_revenue']:.2f}",
        roi=stats["roi"],
        api_rows=api_rows or "<tr><td colspan='4'>No API calls recorded</td></tr>",
        rolling_rows=rolling_rows or "<tr><td colspan='4'>No data yet</td></tr>",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )


# ---------------------------------------------------------------------------
# Send email via SendGrid
# ---------------------------------------------------------------------------


def send_report_email(html_body: str, subject: str = "") -> bool:
    """Send the HTML report to the configured recipient via SendGrid."""
    if not config.SENDGRID_API_KEY or not config.EMAIL_RECIPIENT:
        logger.warning("SendGrid not configured – skipping email report")
        return False

    try:
        import sendgrid  # type: ignore
        from sendgrid.helpers.mail import Mail  # type: ignore

        if not subject:
            subject = f"Content AI Daily Report – {datetime.now(timezone.utc).date()}"

        message = Mail(
            from_email=config.EMAIL_SENDER,
            to_emails=config.EMAIL_RECIPIENT,
            subject=subject,
            html_content=html_body,
        )
        sg = sendgrid.SendGridAPIClient(api_key=config.SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info("Report email sent (status %d)", response.status_code)
        return response.status_code in (200, 202)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send report email: %s", exc)
        return False


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def export_csv(days: int = 30) -> str:
    """Return a CSV string of the last *days* daily stats."""
    rows = collect_rolling_stats(days)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["date", "videos_count", "total_cost", "estimated_revenue"],
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_daily_report() -> bool:
    """Collect today's stats, build and send the HTML report."""
    stats = collect_daily_stats()
    html = build_html_report(stats)
    success = send_report_email(html)

    # Also save the HTML to disk
    report_path = config.LOGS_DIR / f"report_{stats['date']}.html"
    try:
        report_path.write_text(html, encoding="utf-8")
        logger.info("Report saved: %s", report_path)
    except OSError as exc:
        logger.warning("Could not save report to disk: %s", exc)

    return success
