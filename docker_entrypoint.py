"""Initialize the production schema once, then replace this process with Gunicorn.

Migrations (not ``db.create_all``) are the source of truth for schema changes:
``create_all`` only ever creates *missing* tables, so it silently skips the
column additions and drops that a released migration would apply. Running
``flask db upgrade`` once here — before Gunicorn forks — also keeps N workers
from racing on DDL.

Set ``SKIP_MIGRATIONS=1`` to bypass this step when an operator applies schema
changes out of band (a release job, a managed migration service).
"""
import os

from app import create_app


def main() -> None:
    app = create_app(os.environ.get("FLASK_CONFIG", "production"))

    if os.environ.get("SKIP_MIGRATIONS", "").lower() not in {"1", "true", "yes"}:
        from flask_migrate import upgrade

        with app.app_context():
            upgrade()

    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "-w", os.environ.get("WEB_CONCURRENCY", "4"),
            "-b", f"0.0.0.0:{os.environ.get('PORT', '8000')}",
            "--access-logfile", "-",
            "run:app",
        ],
    )


if __name__ == "__main__":
    main()
