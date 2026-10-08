"""Evaluate saved-search alerts for the prototype's scheduled console delivery."""
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.user import JobAlert
from app.services.params import bounded_int, nonnegative_float
from app.services.search import search_jobs


FREQUENCY_INTERVALS = {
    "instant": timedelta(minutes=15),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def due_alert_deliveries(now: datetime | None = None) -> list[dict]:
    """Return due alert payloads and advance their delivery cursor atomically.

    The prototype worker logs these payloads. A production mail adapter can send
    the same structure through SMTP/SES without changing search semantics.
    """
    now = _aware(now or datetime.now(timezone.utc))
    deliveries = []
    alerts = (db.session.query(JobAlert)
              .filter_by(active=True)
              .order_by(JobAlert.created_at.asc()).all())
    for alert in alerts:
        interval = FREQUENCY_INTERVALS.get(alert.frequency, FREQUENCY_INTERVALS["daily"])
        cursor = _aware(alert.last_sent_at or alert.created_at)
        if alert.last_sent_at and now - cursor < interval:
            continue

        criteria = alert.query if isinstance(alert.query, dict) else {}
        result = search_jobs(
            q=str(criteria.get("q", "")),
            location=str(criteria.get("location", "")),
            employment_type=str(criteria.get("type", "")),
            category=str(criteria.get("category", "")),
            salary_min=nonnegative_float(criteria.get("salary_min")),
            remote_only=str(criteria.get("remote", "")) == "1",
            freshness_days=bounded_int(criteria.get("freshness"), 0, 0, 365) or None,
            per_page=100,
        )
        jobs = []
        for job in result["jobs"]:
            seen = job.posted_at or job.first_seen_at or job.created_at
            if seen and _aware(seen) >= cursor:
                jobs.append(job)

        deliveries.append({
            "alert_id": alert.id,
            "name": alert.name,
            "recipient": alert.user.email if alert.user else "",
            "jobs": jobs,
            "unsubscribe_token": alert.unsubscribe_token,
        })
        alert.last_sent_at = now

    db.session.commit()
    return deliveries
