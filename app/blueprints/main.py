"""Main blueprint: home, about, health check, robots.txt and sitemap.xml."""
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, Response, render_template, request, url_for
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.job import Company, Job, Source
from app.services.search import get_categories, recent_jobs

bp = Blueprint("main", __name__)

# Keep the generated sitemap bounded — search engines only need a representative
# crawl surface, and this keeps the response fast on a large index.
SITEMAP_JOB_LIMIT = 5000


@bp.route("/")
def home():
    jobs = recent_jobs(10)
    total_jobs = db.session.query(func.count(Job.id)).filter(Job.status == "active").scalar() or 0
    total_sources = db.session.query(func.count(Source.id)).filter(Source.enabled.is_(True)).scalar() or 0
    return render_template(
        "home.html",
        jobs=jobs,
        total_jobs=total_jobs,
        total_sources=total_sources,
        categories=get_categories(),
        q=request.args.get("q", "").strip(),
        location=request.args.get("location", "").strip(),
    )


@bp.route("/about")
def about():
    return render_template("about.html")


@bp.route("/healthz")
def healthz():
    """Liveness/readiness probe used by the container and PaaS health checks."""
    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.session.rollback()
        return {"status": "unhealthy", "database": "unavailable"}, 503
    return {"status": "ok", "database": "ok"}, 200


@bp.route("/robots.txt")
def robots():
    """Allow the public catalogue; keep authenticated workspaces out of the index."""
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /account",
        "Disallow: /admin",
        "Disallow: /api/",
        "Disallow: /alerts",
        "Disallow: /applications",
        "Disallow: /employer",
        "Disallow: /resume",
        "Disallow: /saved",
        f"Sitemap: {url_for('main.sitemap', _external=True)}",
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@bp.route("/sitemap.xml")
def sitemap():
    """Public crawl surface: home, search, active job details and company pages."""
    urls = [
        (url_for("main.home", _external=True), "1.0", "daily"),
        (url_for("jobs.search", _external=True), "0.9", "hourly"),
        (url_for("main.about", _external=True), "0.4", "monthly"),
    ]

    job_rows = db.session.execute(
        select(Job.id, Job.updated_at)
        .where(Job.status == "active")
        .order_by(Job.last_seen_at.desc())
        .limit(SITEMAP_JOB_LIMIT)
    ).all()
    for job_id, updated_at in job_rows:
        urls.append((
            url_for("jobs.detail", job_id=job_id, _external=True),
            "0.7",
            updated_at.strftime("%Y-%m-%d") if updated_at else None,
        ))

    company_slugs = db.session.execute(select(Company.slug)).scalars().all()
    for slug in company_slugs:
        urls.append((url_for("jobs.company", slug=slug, _external=True), "0.5", None))

    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, priority, lastmod in urls:
        parts.append("<url>")
        # URLs are built from user-supplied company slugs, so the value is
        # escaped: an unescaped "&" would produce a malformed sitemap and an
        # unescaped "<" could break out of the <loc> element entirely.
        parts.append(f"<loc>{xml_escape(loc)}</loc>")
        if lastmod:
            parts.append(f"<lastmod>{lastmod}</lastmod>")
        parts.append(f"<priority>{priority}</priority>")
        parts.append("</url>")
    parts.append("</urlset>")

    return Response("\n".join(parts), mimetype="application/xml")
