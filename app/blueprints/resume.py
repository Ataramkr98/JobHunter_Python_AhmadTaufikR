"""Resume builder (Phase 2): build/edit resume, preview, AI job matches."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.employer import Resume
from app.services import resume as resume_svc
from app.services.matching import match_jobs, resume_to_profile_text

bp = Blueprint("resume", __name__, url_prefix="/resume")


@bp.route("", methods=["GET", "POST"])
@bp.route("/", methods=["GET", "POST"])
@login_required
def builder():
    resume = current_user.active_resume
    if request.method == "POST":
        if resume is None:
            resume = Resume(user_id=current_user.id)
            db.session.add(resume)
        resume.full_name = request.form.get("full_name", "").strip()
        resume.headline = request.form.get("headline", "").strip()
        resume.email = request.form.get("email", "").strip() or current_user.email
        resume.phone = request.form.get("phone", "").strip()
        resume.location = request.form.get("location", "").strip()
        resume.summary = request.form.get("summary", "").strip()
        resume.skills = resume_svc.parse_list(request.form.get("skills", ""))
        resume.links = {
            "linkedin": resume_svc.safe_web_url(request.form.get("linkedin", "")),
            "github": resume_svc.safe_web_url(request.form.get("github", "")),
            "portfolio": resume_svc.safe_web_url(request.form.get("portfolio", "")),
        }
        resume.experiences = resume_svc.parse_experiences(
            request.form.getlist("exp_role"), request.form.getlist("exp_company"),
            request.form.getlist("exp_start"), request.form.getlist("exp_end"),
            request.form.getlist("exp_desc"))
        resume.educations = resume_svc.parse_educations(
            request.form.getlist("edu_degree"), request.form.getlist("edu_school"),
            request.form.getlist("edu_year"))
        db.session.commit()
        flash("Resume saved.", "success")
        return redirect(url_for("resume.preview"))

    percent, checks = (0, [])
    if resume:
        percent, checks = resume_svc.completeness(resume)
    return render_template("resume/builder.html", resume=resume, percent=percent, checks=checks)


@bp.route("/preview")
@login_required
def preview():
    resume = current_user.active_resume
    if not resume:
        flash("Build your resume first.", "info")
        return redirect(url_for("resume.builder"))
    percent, _ = resume_svc.completeness(resume)
    return render_template("resume/preview.html", resume=resume, percent=percent)


@bp.route("/matches")
@login_required
def matches():
    resume = current_user.active_resume
    if not resume:
        flash("Build your resume to get AI job matches.", "info")
        return redirect(url_for("resume.builder"))
    results = match_jobs(resume_to_profile_text(resume), top_n=12, profile_skills=resume.skills)
    return render_template("resume/matches.html", resume=resume, results=results)
