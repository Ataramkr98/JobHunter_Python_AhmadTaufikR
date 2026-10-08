"""Application factory (create_app) — the PRD's recommended Flask pattern.

- Extensions are initialized via init_app (no circular imports).
- Blueprints are organized by domain (jobs, accounts, alerts, employer, resume, admin, api).
- Routes stay thin; business logic lives in app/services/.
- Error handling, security headers and production config validation are applied here.
"""
import os
from pathlib import Path

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from config import config_by_name, validate_config
from app.extensions import db, migrate, login_manager, csrf
from app.errors import register_error_handlers, register_security_headers


def _configure_proxy(app: Flask) -> None:
    """Trust X-Forwarded-* from a known number of upstream proxies.

    The bundled Nginx (and most PaaS routers) terminate TLS and forward the
    original scheme/host. Without this, ``url_for(_external=True)`` would emit
    ``http://`` links and ``request.remote_addr`` would be the proxy's address.
    """
    trusted = int(app.config.get("TRUSTED_PROXIES", 0) or 0)
    if trusted > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=trusted, x_proto=trusted, x_host=trusted, x_port=trusted, x_prefix=trusted,
        )


def create_app(config_name: str | None = None) -> Flask:
    if config_name is None:
        config_name = os.environ.get("FLASK_CONFIG", "development")

    if config_name not in config_by_name:
        valid = ", ".join(sorted(config_by_name))
        raise ValueError(f"Unknown FLASK_CONFIG {config_name!r}; expected one of: {valid}")

    app = Flask(__name__)
    app.config.from_object(config_by_name[config_name])

    # Ensure the instance dir exists so SQLite can create its file.
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    _configure_proxy(app)
    # Refuse to boot production with a default secret key or a SQLite database.
    validate_config(app)

    # --- Initialize extensions ---
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # --- Cross-cutting HTTP behaviour ---
    register_error_handlers(app)
    register_security_headers(app)

    # --- Register models + user loader ---
    from app import models as _models  # noqa: F401  (registers all models on the metadata)
    del _models
    from app.models.user import User

    @login_manager.user_loader
    def load_user(user_id):
        try:
            user = db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None
        return user if user and user.deleted_at is None else None

    # --- Register blueprints (domain modules) ---
    from app.blueprints.main import bp as main_bp
    from app.blueprints.jobs import bp as jobs_bp
    from app.blueprints.accounts import bp as accounts_bp
    from app.blueprints.alerts import bp as alerts_bp
    from app.blueprints.employer import bp as employer_bp
    from app.blueprints.resume import bp as resume_bp
    from app.blueprints.admin import bp as admin_bp
    from app.blueprints.api import bp as api_bp

    for blueprint in (main_bp, jobs_bp, accounts_bp, alerts_bp,
                      employer_bp, resume_bp, admin_bp, api_bp):
        app.register_blueprint(blueprint)

    # Prototype convenience. Production initializes once in docker_entrypoint.py
    # before Gunicorn forks, avoiding concurrent DDL from multiple workers.
    if app.config.get("AUTO_CREATE_DB", True):
        with app.app_context():
            db.create_all()

    # --- Template filters ---
    # Cron strings are stored for the scheduler, not for humans; render them as
    # prose so the source-health dashboard reads "every 6 hours".
    @app.template_filter("cron")
    def _cron(expression):
        from app.services.cron import describe_cron
        return describe_cron(expression)

    # --- Global template context ---
    @app.context_processor
    def inject_globals():
        from app.services.search import get_categories

        return {
            "nav_categories": get_categories(),
            # Rendered into the register/reset password hints so the copy can
            # never disagree with the server-side check in accounts.py.
            "min_password_length": app.config.get("MIN_PASSWORD_LENGTH", 8),
        }

    _register_cli(app)
    return app


def _register_cli(app: Flask) -> None:
    """Operational commands: `flask init-db` and `flask check-config`."""
    import click

    @app.cli.command("init-db")
    def init_db():
        """Create any missing tables. Safe to run on every deploy."""
        db.create_all()
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        backend = "PostgreSQL" if uri.startswith("postgresql") else "SQLite"
        click.echo(f"Schema is up to date on {backend}.")

    @app.cli.command("check-config")
    def check_config():
        """Print the effective configuration without leaking secrets."""
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        click.echo(f"config          : {os.environ.get('FLASK_CONFIG', 'development')}")
        click.echo(f"debug           : {app.debug}")
        click.echo(f"database backend: {'postgresql' if uri.startswith('postgresql') else 'sqlite'}")
        click.echo(f"secure cookies  : {app.config.get('SESSION_COOKIE_SECURE', False)}")
        click.echo(f"login rate limit: {app.config.get('LOGIN_RATE_LIMIT')} "
                   f"per {app.config.get('LOGIN_RATE_WINDOW')}s")
