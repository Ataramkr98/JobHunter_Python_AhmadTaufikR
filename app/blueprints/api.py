"""Public JSON API.

Every response uses the same envelope so clients have one shape to parse::

    {"success": true,  "message": "", "data": {...}}
    {"success": false, "message": "...", "data": {}, "error": {...}}

Endpoints
---------
GET  /api/jobs          search the index (filters, sorting, pagination)
GET  /api/jobs/<id>     a single job with its source links
GET  /api/categories    the active category facets
POST /api/match         rank jobs against a resume or a supplied profile text
"""
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app.extensions import csrf
from app.models.job import Job
from app.services.matching import match_jobs, resume_to_profile_text
from app.services.params import bounded_int, nonnegative_float
from app.services.ratelimit import register_hit, seconds_until_retry
from app.services.search import get_categories, search_jobs

bp = Blueprint("api", __name__, url_prefix="/api")
# Read-only endpoints are CSRF-exempt; /api/match accepts a body but performs no
# state change and requires no session, so exempting the blueprint is safe here.
csrf.exempt(bp)


def api_ok(data, message: str = "", status: int = 200):
    return jsonify({"success": True, "message": message, "data": data}), status


def api_error(message: str, status: int = 400, **details):
    body = {"success": False, "message": message, "data": {}}
    if details:
        body["error"] = details
    return jsonify(body), status


@bp.before_request
def enforce_api_rate_limit():
    """Budget the unauthenticated API per client.

    ``GET /api/jobs`` is a cheap indexed query, but ``POST /api/match`` builds a
    TF-IDF matrix over the whole active corpus on every call. Without a cap a
    single client can pin a CPU, so the expensive endpoint gets its own limit
    and the response says how long to wait.
    """
    limit = current_app.config.get("API_RATE_LIMIT", 0)
    window = current_app.config.get("API_RATE_WINDOW", 60)
    if not limit:
        return None
    # Key on the proxy-resolved address (see ProxyFix in create_app) so a
    # forwarded header cannot be used to dodge the limit.
    key = f"api:{request.endpoint or request.path}:{request.remote_addr or 'unknown'}"
    if register_hit(key, window) > limit:
        retry = seconds_until_retry(key, window)
        # A `before_request` handler short-circuits the view only when it returns
        # a response *or* a (response, status) tuple — returning just the body
        # would silently answer 200.
        body, status = api_error(
            "Rate limit exceeded. Try again shortly.", 429,
            retry_after_seconds=retry,
        )
        body.headers["Retry-After"] = str(retry)
        return body, status
    return None


def _job_summary(job: Job) -> dict:
    return {
        "id": job.id,
        "title": job.title,
        "canonical_title": job.canonical_title,
        "company": {"name": job.company.name, "slug": job.company.slug},
        "location": {"city": job.city, "region": job.region, "is_remote": job.is_remote},
        "employment_type": job.employment_type,
        "seniority": job.seniority,
        "category": job.category,
        "salary": {
            "min": float(job.salary_min) if job.salary_min is not None else None,
            "max": float(job.salary_max) if job.salary_max is not None else None,
            "currency": job.salary_currency,
            "period": job.salary_period,
            "display": job.salary_display,
        },
        "skills": job.skills or [],
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "url": f"/jobs/{job.id}",
    }


@bp.route("/jobs")
def jobs():
    args = request.args
    result = search_jobs(
        q=args.get("q", ""), location=args.get("location", ""),
        employment_type=args.get("type", ""), category=args.get("category", ""),
        salary_min=nonnegative_float(args.get("salary_min")),
        remote_only=args.get("remote") == "1",
        freshness_days=bounded_int(args.get("freshness"), 0, 0, 365) or None,
        sort=args.get("sort", "newest"),
        page=bounded_int(args.get("page"), 1, 1, 100000),
        per_page=bounded_int(args.get("per_page"), 10, 1, 100),
    )
    return api_ok({
        "jobs": [_job_summary(j) for j in result["jobs"]],
        "pagination": {
            "total": result["total"],
            "page": result["page"],
            "pages": result["pages"],
            "per_page": result["per_page"],
        },
    })


@bp.route("/jobs/<int:job_id>")
def job_detail(job_id):
    job = Job.query.filter_by(id=job_id, status="active").first()
    if not job:
        return api_error("Job not found.", 404)
    payload = _job_summary(job)
    payload["description"] = job.description
    payload["sources"] = [
        {"name": link.source.name, "url": link.url}
        for link in job.job_sources
    ]
    return api_ok(payload)


@bp.route("/categories")
def categories():
    return api_ok({"categories": get_categories()})


@bp.route("/match", methods=["POST"])
def match():
    """Rank active jobs against a profile. Uses the caller's resume when signed in."""
    profile_text, skills = "", []
    if current_user.is_authenticated and current_user.active_resume:
        resume = current_user.active_resume
        profile_text = resume_to_profile_text(resume)
        skills = resume.skills or []

    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return api_error("JSON body must be an object.", 400)

    if isinstance(data.get("profile_text"), str) and data["profile_text"].strip():
        profile_text = data["profile_text"]
        skills = data.get("skills", [])
        if not isinstance(skills, list):
            return api_error("`skills` must be an array of strings.", 400)
    if not isinstance(profile_text, str) or not profile_text.strip():
        return api_error("No profile or resume text to match. Sign in with a resume, "
                         "or send `profile_text` in the request body.", 400)

    top_n = bounded_int(data.get("top_n"), 10, 1, 100)
    results = match_jobs(profile_text, top_n=top_n, profile_skills=skills)
    return api_ok({
        "matches": [{
            "id": r["job"].id,
            "title": r["job"].title,
            "company": r["job"].company.name,
            "city": r["job"].city,
            "score": r["score"],
            "matched_skills": r["matched_skills"],
        } for r in results],
    })
