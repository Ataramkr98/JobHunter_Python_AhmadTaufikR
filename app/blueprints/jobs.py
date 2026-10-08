"""Jobs blueprint: search, detail, company, save, track."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import SavedJob, Application
from app.models.employer import PostedJob
from app.services import search as search_svc
from app.services.matching import fit_score, resume_to_profile_text
from app.services.params import bounded_int, nonnegative_float
from app.services.urls import safe_local_path

bp = Blueprint("jobs", __name__)


@bp.route("/jobs")
def search():
    args = request.args
    filters = {
        "q": args.get("q", "").strip(),
        "location": args.get("location", "").strip(),
        "type": args.get("type", "").strip(),
        "category": args.get("category", "").strip(),
        "salary_min": args.get("salary_min", "").strip(),
        "remote": args.get("remote", "").strip(),
        "freshness": args.get("freshness", "").strip(),
        "sort": args.get("sort", "").strip(),
    }
    result = search_svc.search_jobs(
        q=filters["q"],
        location=filters["location"],
        employment_type=filters["type"],
        category=filters["category"],
        salary_min=nonnegative_float(filters["salary_min"]),
        remote_only=filters["remote"] == "1",
        freshness_days=bounded_int(filters["freshness"], 0, 0, 365) or None,
        sort=filters["sort"] or "newest",
        page=bounded_int(args.get("page"), 1, 1, 100000),
        per_page=10,
    )
    saved_ids = set()
    if current_user.is_authenticated:
        saved_ids = {s.job_id for s in current_user.saved_jobs}
    # Only the filters the user actually set, so pagination links stay clean and
    # `page` is never duplicated by the macro.
    page_params = {key: value for key, value in filters.items() if value}
    return render_template(
        "jobs/search.html", result=result, args=args,
        types=search_svc.EMPLOYMENT_TYPES,
        categories=search_svc.get_categories(), saved_ids=saved_ids,
        page_params=page_params,
    )


@bp.route("/jobs/<int:job_id>")
def detail(job_id):
    job = search_svc.get_job_or_none(job_id)
    if not job or job.status != "active":
        abort(404)
    saved = applied = submitted = False
    fit = None
    posted_job = PostedJob.query.filter_by(job_id=job.id).first()
    if current_user.is_authenticated:
        saved = SavedJob.query.filter_by(user_id=current_user.id, job_id=job.id).first() is not None
        application = Application.query.filter_by(user_id=current_user.id, job_id=job.id).first()
        applied = application is not None
        submitted = bool(posted_job and application and application.posted_job_id == posted_job.id)
        resume = current_user.active_resume
        if resume:
            fit = fit_score(resume_to_profile_text(resume), resume.skills, job)
    similar = [j for j in search_svc.search_jobs(category=job.category, per_page=5)["jobs"] if j.id != job.id][:3]

    # One "Apply on X" link per portal. A listing that was scraped twice from the
    # same board would otherwise render two identical buttons.
    apply_links, seen_sources = [], set()
    for link in job.job_sources:
        if link.source.name == "Employer Portal" or link.source_id in seen_sources:
            continue
        seen_sources.add(link.source_id)
        apply_links.append(link)

    return render_template(
        "jobs/detail.html", job=job, posted_job=posted_job, saved=saved,
        applied=applied, submitted=submitted, fit=fit, similar=similar,
        apply_links=apply_links,
    )


@bp.route("/companies/<slug>")
def company(slug):
    company = search_svc.get_company_by_slug(slug)
    if not company:
        abort(404)
    jobs = [j for j in company.jobs if j.status == "active"]
    return render_template("jobs/company.html", company=company, jobs=jobs)


@bp.route("/jobs/<int:job_id>/save", methods=["POST"])
@login_required
def save(job_id):
    job = search_svc.get_job_or_none(job_id) or abort(404)
    if job.status != "active":
        abort(404)
    existing = SavedJob.query.filter_by(user_id=current_user.id, job_id=job.id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash("Removed from saved jobs.", "info")
    else:
        db.session.add(SavedJob(user_id=current_user.id, job_id=job.id))
        db.session.commit()
        flash("Job saved.", "success")
    return redirect(safe_local_path(request.referrer, url_for("jobs.detail", job_id=job.id)))


@bp.route("/jobs/<int:job_id>/track", methods=["POST"])
@login_required
def track(job_id):
    job = search_svc.get_job_or_none(job_id) or abort(404)
    if job.status != "active":
        abort(404)
    if PostedJob.query.filter_by(job_id=job.id).first():
        flash("Use the employer application form for this job.", "info")
        return redirect(url_for("jobs.detail", job_id=job.id))
    if not Application.query.filter_by(user_id=current_user.id, job_id=job.id).first():
        db.session.add(Application(user_id=current_user.id, job_id=job.id, status="applied"))
        db.session.commit()
        flash("Added to your application tracker.", "success")
    else:
        flash("Already in your tracker.", "info")
    return redirect(safe_local_path(request.referrer, url_for("jobs.detail", job_id=job.id)))
