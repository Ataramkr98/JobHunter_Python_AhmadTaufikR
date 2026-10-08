"""Admin blueprint: per-source scrape health + moderation (FR-G)."""
from functools import wraps

from flask import Blueprint, render_template, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models.job import Source, ScrapeRun, Job

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return wrapper


@bp.route("", methods=["GET"])
@bp.route("/", methods=["GET"])
@admin_required
def dashboard():
    sources = Source.query.order_by(Source.name).all()
    runs = ScrapeRun.query.order_by(ScrapeRun.started_at.desc()).limit(20).all()
    total_jobs = db.session.query(func.count(Job.id)).scalar() or 0
    active_jobs = db.session.query(func.count(Job.id)).filter(Job.status == "active").scalar() or 0

    source_stats = {}
    for s in sources:
        last = ScrapeRun.query.filter_by(source_id=s.id).order_by(ScrapeRun.started_at.desc()).first()
        total = ScrapeRun.query.filter_by(source_id=s.id).count()
        ok = ScrapeRun.query.filter_by(source_id=s.id, status="success").count()
        source_stats[s.id] = {
            "last": last,
            "success_rate": (ok / total * 100) if total else 0.0,
            "runs": total,
        }
    return render_template("admin/dashboard.html", sources=sources, runs=runs,
                           total_jobs=total_jobs, active_jobs=active_jobs, source_stats=source_stats)


@bp.route("/sources/<int:source_id>/toggle", methods=["POST"])
@admin_required
def toggle_source(source_id):
    source = db.get_or_404(Source, source_id)
    source.enabled = not source.enabled
    db.session.commit()
    flash(f"{source.name} {'enabled' if source.enabled else 'disabled'}.", "info")
    return redirect(url_for("admin.dashboard"))
