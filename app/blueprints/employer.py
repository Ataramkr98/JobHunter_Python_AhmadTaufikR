"""Employer portal (Phase 2): become an employer, post jobs, view applicants.

Posted jobs also create a canonical `Job` (source = 'Employer Portal') so they
appear in search and AI matching exactly like scraped jobs.
"""
import re
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models.employer import Employer, PostedJob
from app.models.job import Job, Company, Source, JobSource
from app.models.user import Application
from app.services.normalization import normalize_job
from app.services.dedup import dedup_hash
from app.services.resume import safe_web_url

bp = Blueprint("employer", __name__, url_prefix="/employer")


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "company"


def _employer_required() -> Employer:
    if not current_user.is_authenticated or not current_user.is_employer or not current_user.employer:
        abort(403)
    return current_user.employer


def _get_or_create_company(name: str) -> Company:
    company = Company.query.filter(func.lower(Company.name) == name.lower()).first()
    if company:
        return company

    base_slug = _slugify(name)
    slug = base_slug
    suffix = 2
    while Company.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{suffix}"
        suffix += 1
    company = Company(name=name, slug=slug)
    db.session.add(company)
    db.session.flush()
    return company


def _employer_source() -> Source:
    source = Source.query.filter_by(name="Employer Portal").first()
    if not source:
        source = Source(name="Employer Portal", base_url="/employer", engine="api",
                        robots_status="n/a", enabled=True)
        db.session.add(source)
        db.session.flush()
    return source


@bp.route("", methods=["GET"])
@bp.route("/", methods=["GET"])
@login_required
def dashboard():
    if not current_user.is_employer or not current_user.employer:
        return render_template("employer/become.html")
    employer = current_user.employer
    posted = PostedJob.query.filter_by(employer_id=employer.id).order_by(PostedJob.created_at.desc()).all()
    counts = {pj.id: Application.query.filter_by(posted_job_id=pj.id).count() for pj in posted}
    return render_template("employer/dashboard.html", employer=employer, posted=posted, counts=counts)


@bp.route("/become", methods=["POST"])
@login_required
def become():
    if current_user.employer:
        if not current_user.is_employer:
            current_user.is_employer = True
            db.session.commit()
        return redirect(url_for("employer.dashboard"))
    company_name = request.form.get("company_name", "").strip()
    if not company_name:
        flash("Company name is required.", "error")
        return redirect(url_for("employer.dashboard"))
    company = _get_or_create_company(company_name)
    description = request.form.get("description", "").strip()
    website = safe_web_url(request.form.get("website", ""))
    if not company.description and description:
        company.description = description
    if not company.website and website:
        company.website = website
    employer = Employer(
        user_id=current_user.id, company_name=company_name,
        company_id=company.id,
        description=description,
        website=website,
    )
    current_user.is_employer = True
    db.session.add(employer)
    db.session.commit()
    flash("Employer account created — you can now post jobs.", "success")
    return redirect(url_for("employer.dashboard"))


@bp.route("/post", methods=["GET", "POST"])
@login_required
def post():
    employer = _employer_required()
    if request.method == "POST":
        employment_type = request.form.get("employment_type", "full_time")
        if employment_type not in {"full_time", "part_time", "contract", "intern"}:
            employment_type = "full_time"
        raw = {
            "title": request.form.get("title", "").strip(),
            "location": request.form.get("location", "").strip(),
            "employment_type": employment_type,
            "salary": request.form.get("salary", "").strip(),
            "description": request.form.get("description", "").strip(),
            "skills": [s.strip() for s in request.form.get("skills", "").split(",") if s.strip()],
        }
        if not raw["title"]:
            flash("Job title is required.", "error")
            return render_template("employer/post.html")

        norm = normalize_job(raw)
        norm["employment_type"] = raw["employment_type"]  # employer selects directly

        company = _get_or_create_company(employer.company_name)
        if employer.company_id != company.id:
            employer.company_id = company.id
        source = _employer_source()

        job = Job(company_id=company.id, posted_at=datetime.now(timezone.utc),
                  status="active", **norm)
        job.dedup_hash = dedup_hash(company.name, norm["title"], norm["location_raw"], norm["is_remote"])
        db.session.add(job)
        db.session.flush()
        db.session.add(JobSource(job_id=job.id, source_id=source.id,
                                 external_id=f"posted-{job.id}",
                                 url=url_for("jobs.detail", job_id=job.id)))
        pj = PostedJob(
            employer_id=employer.id, job_id=job.id, title=norm["title"],
            description=norm["description"], location=norm["location_raw"],
            employment_type=norm["employment_type"], salary_min=norm["salary_min"],
            salary_max=norm["salary_max"], salary_currency=norm["salary_currency"],
            category=norm["category"], status="active",
        )
        db.session.add(pj)
        db.session.commit()
        flash("Job posted! It's now live in search and AI matching.", "success")
        return redirect(url_for("employer.dashboard"))
    return render_template("employer/post.html")


@bp.route("/jobs/<int:pj_id>")
@login_required
def applicants(pj_id):
    employer = _employer_required()
    pj = PostedJob.query.filter_by(id=pj_id, employer_id=employer.id).first_or_404()
    apps = Application.query.filter_by(posted_job_id=pj.id).order_by(Application.created_at.desc()).all()
    return render_template("employer/applicants.html", pj=pj, applications=apps)


@bp.route("/jobs/<int:pj_id>/close", methods=["POST"])
@login_required
def close(pj_id):
    employer = _employer_required()
    pj = PostedJob.query.filter_by(id=pj_id, employer_id=employer.id).first_or_404()
    if pj.status == "closed":
        flash("Job is already closed.", "info")
        return redirect(url_for("employer.dashboard"))
    pj.status = "closed"
    if pj.job:
        pj.job.status = "expired"
    db.session.commit()
    flash("Job closed.", "info")
    return redirect(url_for("employer.dashboard"))


@bp.route("/jobs/<int:pj_id>/apply", methods=["POST"])
@login_required
def apply(pj_id):
    pj = PostedJob.query.filter_by(id=pj_id).first_or_404()
    if not pj.job or pj.status != "active" or pj.job.status != "active":
        abort(404)
    if pj.employer.user_id == current_user.id:
        flash("You cannot apply to your own job posting.", "error")
        return redirect(url_for("jobs.detail", job_id=pj.job_id))

    existing = Application.query.filter_by(user_id=current_user.id, job_id=pj.job_id).first()
    if existing and existing.posted_job_id == pj.id:
        flash("You already applied to this job.", "info")
    elif existing:
        # Convert a previously self-tracked record into a real employer application.
        existing.posted_job_id = pj.id
        existing.cover_note = request.form.get("cover_note", "").strip()
        existing.status = "applied"
        db.session.commit()
        flash("Application submitted to the employer.", "success")
    else:
        db.session.add(Application(
            user_id=current_user.id, job_id=pj.job_id, posted_job_id=pj.id,
            status="applied", cover_note=request.form.get("cover_note", "").strip()))
        db.session.commit()
        flash("Application submitted to the employer.", "success")
    return redirect(url_for("jobs.detail", job_id=pj.job_id))
