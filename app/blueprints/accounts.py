"""Accounts blueprint: auth, saved jobs, application tracker, profile, erasure."""
from datetime import datetime, timezone

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from email_validator import EmailNotValidError, validate_email

from app.extensions import db
from app.models.user import Application, PasswordResetToken, SavedJob, User
from app.services.mail import Message, deliver
from app.services.ratelimit import hit_count, register_hit, reset, seconds_until_retry
from app.services.urls import safe_local_path

bp = Blueprint("accounts", __name__)


# --------------------------------------------------------------------------- #
# Credential-endpoint protection
# --------------------------------------------------------------------------- #
def _limit_key(scope: str, email: str = "") -> str:
    """Key the limiter on the client address.

    ``request.remote_addr`` already reflects ``X-Forwarded-For`` when the app
    runs behind a trusted proxy (see ProxyFix in create_app), so reading the
    header directly here would let a caller spoof their own identity.
    """
    return f"{scope}:{request.remote_addr or 'unknown'}:{(email or '').lower()}"


def _retry_after(scope: str, email: str = "") -> int:
    """Seconds the caller must wait, or 0 when they are still under the limit."""
    limit = current_app.config.get("LOGIN_RATE_LIMIT", 0)
    if not limit:
        return 0
    window = current_app.config.get("LOGIN_RATE_WINDOW", 300)
    key = _limit_key(scope, email)
    if hit_count(key, window) >= limit:
        return seconds_until_retry(key, window)
    return 0


def _record_failure(scope: str, email: str = "") -> None:
    if current_app.config.get("LOGIN_RATE_LIMIT", 0):
        register_hit(_limit_key(scope, email), current_app.config.get("LOGIN_RATE_WINDOW", 300))


def _clear_failures(scope: str, email: str = "") -> None:
    reset(_limit_key(scope, email))


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@bp.route("/auth/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("display_name", "").strip()[:120]
        pw = request.form.get("password", "")

        wait = _retry_after("register", email)
        if wait:
            flash(f"Too many sign-up attempts. Try again in {wait} seconds.", "error")
            return render_template("accounts/register.html"), 429

        minimum = current_app.config.get("MIN_PASSWORD_LENGTH", 8)
        invalid_email = False
        try:
            email = validate_email(email, check_deliverability=False).normalized.lower()
        except EmailNotValidError:
            email = ""
            invalid_email = True
        if invalid_email:
            flash("Enter a valid email address.", "error")
        elif not email or not pw:
            flash("Email and password are required.", "error")
        elif User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
        elif len(pw) < minimum:
            flash(f"Password must be at least {minimum} characters.", "error")
        else:
            user = User(email=email, display_name=name or email.split("@")[0])
            user.set_password(pw)
            db.session.add(user)
            db.session.commit()
            _clear_failures("register", email)
            login_user(user)
            flash("Welcome to JobHunter! Your account is ready.", "success")
            return redirect(url_for("main.home"))
        _record_failure("register", email)
    return render_template("accounts/register.html")


@bp.route("/auth/login", methods=["GET", "POST"])
def login():
    # `request.values` covers both the ?next= query string and the hidden field,
    # and safe_local_path drops anything that is not a same-origin path.
    next_url = safe_local_path(request.values.get("next"), fallback="")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")

        wait = _retry_after("login", email)
        if wait:
            flash(f"Too many failed attempts. Try again in {wait} seconds.", "error")
            return render_template("accounts/login.html", next_url=next_url), 429

        user = User.query.filter_by(email=email, deleted_at=None).first()
        if user and user.check_password(pw):
            _clear_failures("login", email)
            login_user(user)
            flash("Logged in.", "success")
            return redirect(next_url or url_for("main.home"))
        _record_failure("login", email)
        flash("Invalid email or password.", "error")
    return render_template("accounts/login.html", next_url=next_url)


@bp.route("/auth/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for("main.home"))


# --------------------------------------------------------------------------- #
# Password reset
# --------------------------------------------------------------------------- #
# The response is deliberately identical whether or not the address is
# registered. Anything else turns this form into an account-enumeration oracle.
_RESET_NEUTRAL_MESSAGE = (
    "If an account exists for that address, a reset link is on its way. "
    "Check your inbox and spam folder."
)


def _send_reset_email(user: User, plaintext_token: str) -> None:
    link = url_for("accounts.reset_password", token=plaintext_token, _external=True)
    deliver(Message(
        to=user.email,
        subject="Reset your JobHunter password",
        body=(
            f"Hi {user.display_name or 'there'},\n\n"
            "Use the link below to choose a new password. It expires in 30 "
            "minutes and can only be used once.\n\n"
            f"{link}\n\n"
            "If you did not ask for this, you can ignore this email — your "
            "password stays as it is.\n"
        ),
        tags={"kind": "password_reset", "user_id": user.id},
    ))


@bp.route("/auth/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        wait = _retry_after("reset-request", email)
        if wait:
            flash(f"Too many reset attempts. Try again in {wait} seconds.", "error")
            return render_template("accounts/forgot_password.html", email=email), 429

        user = User.query.filter_by(email=email, deleted_at=None).first()
        if user:
            _token, plaintext = user.issue_reset_token()
            db.session.commit()
            _send_reset_email(user, plaintext)

        _record_failure("reset-request", email)
        flash(_RESET_NEUTRAL_MESSAGE, "info")
        return redirect(url_for("accounts.login"))

    return render_template("accounts/forgot_password.html", email="")


@bp.route("/auth/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    row = PasswordResetToken.query.filter_by(
        token_hash=PasswordResetToken.hash_token(token)
    ).first_or_404()

    if not row.is_usable:
        flash("That reset link has expired or was already used. Request a new one.", "error")
        return redirect(url_for("accounts.forgot_password"))

    if request.method == "POST":
        minimum = current_app.config.get("MIN_PASSWORD_LENGTH", 8)
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirm", "")
        if len(password) < minimum:
            flash(f"Password must be at least {minimum} characters.", "error")
        elif password != confirmation:
            flash("The two passwords do not match.", "error")
        else:
            user = row.user
            user.set_password(password)
            row.used_at = datetime.now(timezone.utc)
            # A password change invalidates every existing session.
            db.session.commit()
            logout_user()
            flash("Password updated. Log in with your new password.", "success")
            return redirect(url_for("accounts.login"))

    return render_template("accounts/reset_password.html", token=token, email=row.user.email)


# --------------------------------------------------------------------------- #
# Seeker workspace
# --------------------------------------------------------------------------- #
@bp.route("/saved")
@login_required
def saved():
    items = SavedJob.query.filter_by(user_id=current_user.id).order_by(SavedJob.created_at.desc()).all()
    return render_template("accounts/saved.html", items=items)


@bp.route("/applications", methods=["GET", "POST"])
@login_required
def applications():
    if request.method == "POST":
        app = Application.query.filter_by(
            id=request.form.get("application_id", type=int), user_id=current_user.id).first()
        if app:
            status = request.form.get("status", "")
            if status in {"applied", "interview", "offer", "rejected", "other"}:
                app.status = status
            app.notes = request.form.get("notes", "")
            db.session.commit()
            flash("Application updated.", "success")
        return redirect(url_for("accounts.applications"))
    apps = Application.query.filter_by(user_id=current_user.id).order_by(Application.updated_at.desc()).all()
    return render_template("accounts/applications.html", applications=apps)


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        current_user.display_name = request.form.get("display_name", "").strip()[:120]
        current_user.default_location = request.form.get("default_location", "").strip()[:120]
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("accounts.account"))
    return render_template("accounts/account.html")


@bp.route("/account/delete", methods=["POST"])
@login_required
def delete_account():
    """PDP right to erasure (FR-F4): soft-delete + anonymize personal data."""
    user = current_user._get_current_object()

    # Remove seeker-owned personal records, including notes visible to employers.
    user.saved_jobs.clear()
    user.alerts.clear()
    user.applications.clear()
    user.resumes.clear()

    # Preserve public job/company records, but close postings and erase the
    # employer profile if the deleted account owned one.
    if user.employer:
        for posted in user.employer.posted_jobs:
            posted.status = "closed"
            if posted.job:
                posted.job.status = "expired"
        user.employer.company_name = "Deleted employer"
        user.employer.description = ""
        user.employer.website = ""
        user.employer.company_id = None

    user.deleted_at = datetime.now(timezone.utc)
    user.email = f"deleted-{user.id}@removed.local"
    user.display_name = "Deleted user"
    user.default_location = ""
    user.email_verified_at = None
    user.is_admin = False
    user.is_employer = False
    user.set_password("!disabled!")
    # Drop outstanding reset links too, so a leaked email cannot re-open access.
    for token in user.reset_tokens:
        if token.used_at is None:
            token.used_at = user.deleted_at
    db.session.commit()
    logout_user()
    flash("Your account and personal data have been deleted.", "info")
    return redirect(url_for("main.home"))
