"""Celery app + scheduled scraping tasks (production async layer).

Requires:  pip install celery redis
Run:       celery -A worker.celery_app worker --loglevel=info
           celery -A worker.celery_app beat --loglevel=info
"""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("jobhunter", broker=REDIS_URL, backend=REDIS_URL)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRAPERS_DIR = PROJECT_ROOT / "scrapers"
SPIDER_BY_SOURCE = {
    "Glints": "glints",
    "Kalibrr": "kalibrr",
}

# Scrape enabled sources every 6 hours (PRD NFR-F2 cadence).
celery_app.conf.beat_schedule = {
    "scrape-enabled-sources": {
        "task": "worker.celery_app.scrape_enabled_sources",
        "schedule": 6 * 3600,
    },
    "deliver-due-job-alerts": {
        "task": "worker.celery_app.deliver_due_job_alerts",
        "schedule": 15 * 60,
    },
}


@celery_app.task
def scrape_enabled_sources():
    """Enqueue one scrape task for each enabled source with an implemented spider."""
    from app import create_app
    from app.models.job import Source

    app = create_app()
    with app.app_context():
        sources = [s.name for s in Source.query.filter_by(enabled=True).all()
                   if s.name in SPIDER_BY_SOURCE]
    return [scrape_source.delay(name).id for name in sources]


@celery_app.task
def scrape_source(source_name: str):
    """Run a configured Scrapy spider without a shell and return a compact result."""
    from app import create_app
    from app.extensions import db
    from app.models.job import Source, ScrapeRun

    spider = SPIDER_BY_SOURCE.get(source_name)
    if not spider:
        raise ValueError(f"No spider is configured for source {source_name!r}")

    started_at = datetime.now(timezone.utc)
    command = [sys.executable, "-m", "scrapy", "crawl", spider]
    try:
        completed = subprocess.run(
            command,
            cwd=SCRAPERS_DIR,
            capture_output=True,
            text=True,
            timeout=60 * 30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(
            command,
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "Spider exceeded the 30-minute timeout.",
        )
    if completed.returncode != 0:
        detail = completed.stderr or completed.stdout or "Spider failed"
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        detail = detail[-2000:]
        app = create_app()
        with app.app_context():
            source = Source.query.filter_by(name=source_name).first()
            run = None
            if source:
                run = (ScrapeRun.query.filter_by(source_id=source.id)
                       .filter(ScrapeRun.started_at >= started_at)
                       .order_by(ScrapeRun.started_at.desc()).first())
            if run:
                run.status = "failed"
                run.finished_at = datetime.now(timezone.utc)
                run.errors = max(1, run.errors or 0)
                run.error_detail = detail
            elif source:
                db.session.add(ScrapeRun(
                    source_id=source.id,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    status="failed",
                    errors=1,
                    error_detail=detail,
                ))
            db.session.commit()
        raise RuntimeError(f"{source_name} spider failed: {detail}")
    return {"source": source_name, "spider": spider, "status": "success"}


@celery_app.task
def deliver_due_job_alerts():
    """Evaluate alerts and log delivery payloads (SMTP/SES adapter in production)."""
    from app import create_app
    from app.services.alerts import due_alert_deliveries

    app = create_app()
    with app.app_context():
        deliveries = due_alert_deliveries()
        for delivery in deliveries:
            app.logger.info(
                "Job alert %s for %s: %s new matches",
                delivery["name"],
                delivery["recipient"],
                len(delivery["jobs"]),
            )
        return [{
            "alert_id": item["alert_id"],
            "recipient": item["recipient"],
            "matches": len(item["jobs"]),
        } for item in deliveries]
