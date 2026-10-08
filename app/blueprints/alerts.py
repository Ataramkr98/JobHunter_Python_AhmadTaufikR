"""Alerts blueprint: saved-search email subscriptions (FR-E).

NOTE: the JobAlert model has a column named `query` (the saved-search criteria),
which shadows Flask-SQLAlchemy's `Model.query` class property. We therefore query
via `db.session.query(JobAlert)` instead of `JobAlert.query` here.
"""
import secrets

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.extensions import db
from app.models.user import JobAlert
from app.services.urls import safe_local_path

bp = Blueprint("alerts", __name__)


@bp.route("/alerts")
@login_required
def index():
    alerts = (db.session.query(JobAlert)
              .filter_by(user_id=current_user.id)
              .order_by(JobAlert.created_at.desc()).all())
    return render_template("alerts/alerts.html", alerts=alerts)


@bp.route("/alerts/create", methods=["POST"])
@login_required
def create():
    criteria = {
        "q": request.form.get("q", "").strip(),
        "location": request.form.get("location", "").strip(),
        "type": request.form.get("type", "").strip(),
        "category": request.form.get("category", "").strip(),
        "salary_min": request.form.get("salary_min", "").strip(),
        "remote": request.form.get("remote", "").strip(),
        "freshness": request.form.get("freshness", "").strip(),
    }
    name = request.form.get("name", "").strip()
    if not name:
        name = (criteria["q"] or "All jobs") + (f" in {criteria['location']}" if criteria["location"] else "")
    frequency = request.form.get("frequency", "daily")
    if frequency not in {"instant", "daily", "weekly"}:
        frequency = "daily"
    alert = JobAlert(
        user_id=current_user.id, name=name, query=criteria,
        frequency=frequency,
        unsubscribe_token=secrets.token_urlsafe(24), active=True,
    )
    db.session.add(alert)
    db.session.commit()
    flash("Job alert created — we'll email you new matches.", "success")
    return redirect(safe_local_path(request.referrer, url_for("alerts.index")))


@bp.route("/alerts/<int:alert_id>/toggle", methods=["POST"])
@login_required
def toggle(alert_id):
    alert = db.session.query(JobAlert).filter_by(id=alert_id, user_id=current_user.id).first_or_404()
    alert.active = not alert.active
    db.session.commit()
    flash("Alert updated.", "info")
    return redirect(url_for("alerts.index"))


@bp.route("/alerts/<int:alert_id>/delete", methods=["POST"])
@login_required
def delete(alert_id):
    alert = db.session.query(JobAlert).filter_by(id=alert_id, user_id=current_user.id).first_or_404()
    db.session.delete(alert)
    db.session.commit()
    flash("Alert deleted.", "info")
    return redirect(url_for("alerts.index"))


@bp.route("/alerts/unsubscribe/<token>", methods=["GET", "POST"])
def unsubscribe(token):
    """Confirm, then unsubscribe.

    Alert links arrive inside email clients, which routinely prefetch URLs in
    the background. If a GET could change state, a link preview alone would
    silently stop someone's alerts. GET therefore renders a confirmation page
    and only the explicit POST performs the change.
    """
    alert = db.session.query(JobAlert).filter_by(unsubscribe_token=token).first_or_404()

    if request.method == "POST":
        alert.active = False
        db.session.commit()
        flash("You have been unsubscribed from this alert.", "info")
        return redirect(url_for("main.home"))

    return render_template("alerts/unsubscribe.html", alert=alert)
