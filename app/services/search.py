"""Search service (FR-C).

MVP uses SQL ILIKE + filtering behind a small functional interface so the
production upgrade to Meilisearch (PRD §8.3) only swaps this module.
"""
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, or_, func, desc

from app.extensions import db
from app.models.job import Job, Company

EMPLOYMENT_TYPES = ["full_time", "part_time", "contract", "intern"]


def get_categories() -> list[str]:
    rows = db.session.execute(
        select(Job.category).where(Job.status == "active").distinct()
    ).scalars().all()
    return sorted({r for r in rows if r})


def search_jobs(q: str = "", location: str = "", employment_type: str = "",
                category: str = "", salary_min: float | None = None,
                remote_only: bool = False, freshness_days: int | None = None,
                sort: str = "newest", page: int = 1, per_page: int = 10) -> dict:
    # Keep pagination safe even when this service is called outside the web routes.
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(100, max(1, int(per_page)))
    except (TypeError, ValueError):
        per_page = 10

    stmt = select(Job).join(Company, Job.company_id == Company.id).where(Job.status == "active")

    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(
            Job.title.ilike(like), Job.canonical_title.ilike(like),
            Job.description.ilike(like), Company.name.ilike(like),
            Job.category.ilike(like),
        ))
    if location:
        stmt = stmt.where(or_(Job.city.ilike(f"%{location}%"), Job.region.ilike(f"%{location}%")))
    if employment_type:
        stmt = stmt.where(Job.employment_type == employment_type)
    if category:
        stmt = stmt.where(Job.category == category)
    if salary_min is not None and salary_min >= 0:
        stmt = stmt.where(func.coalesce(Job.salary_max, Job.salary_min) >= salary_min)
    if remote_only:
        stmt = stmt.where(Job.is_remote.is_(True))
    if freshness_days is not None and freshness_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=freshness_days)
        stmt = stmt.where(Job.posted_at >= cutoff)

    # total count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.session.execute(count_stmt).scalar() or 0

    # ordering
    if sort == "salary":
        stmt = stmt.order_by(desc(func.coalesce(Job.salary_max, Job.salary_min)))
    elif sort == "oldest":
        stmt = stmt.order_by(Job.posted_at.asc().nullslast(), Job.last_seen_at.asc())
    else:  # newest (also used for relevance in the MVP)
        stmt = stmt.order_by(Job.posted_at.desc().nullslast(), desc(Job.last_seen_at))

    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    jobs = db.session.execute(
        stmt.offset((page - 1) * per_page).limit(per_page)
    ).scalars().all()

    return {"jobs": jobs, "total": total, "page": page, "pages": pages, "per_page": per_page}


def recent_jobs(limit: int = 10):
    return db.session.execute(
        select(Job).where(Job.status == "active")
        .order_by(Job.posted_at.desc().nullslast(), desc(Job.last_seen_at))
        .limit(limit)
    ).scalars().all()


def get_job_or_none(job_id: int):
    return db.session.get(Job, job_id)


def get_company_by_slug(slug: str):
    return db.session.execute(
        select(Company).where(Company.slug == slug)
    ).scalar_one_or_none()
