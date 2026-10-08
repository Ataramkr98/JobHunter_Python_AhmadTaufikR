"""Application configuration.

Development runs on SQLite for zero-setup portability. Production reads a
PostgreSQL connection string from ``DATABASE_URL`` — Neon, Supabase, RDS or the
bundled docker-compose Postgres all work, because the URL is normalised before it
reaches SQLAlchemy (see :func:`normalize_database_url`).

Environment variables
---------------------
``FLASK_CONFIG``        development | production | testing
``SECRET_KEY``          required in production (the app refuses to boot without it)
``DATABASE_URL``        PostgreSQL URL; SQLite is used when unset
``DB_POOL_SIZE``        connection pool size for PostgreSQL (default 5)
``DB_MAX_OVERFLOW``     extra connections above the pool size (default 10)
``MAIL_DEFAULT_SENDER`` From-address used by job-alert email
``LOGIN_RATE_LIMIT``    max failed logins per window (default 8)
``LOGIN_RATE_WINDOW``   window in seconds for the login limit (default 300)
"""
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BASE_DIR = Path(__file__).resolve().parent

# Load a local .env when present so the documented workflow ("copy .env.example to
# .env and edit") actually works. Real environment variables always win.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover - dotenv is a convenience, not a requirement
    pass

_TRUTHY = {"1", "true", "t", "yes", "y", "on"}

# libpq understands `channel_binding` from v13 onwards; older client libraries
# reject the keyword outright, so we only forward it when it is safe to do so.
_CHANNEL_BINDING_MIN_LIBPQ = 130000


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _libpq_version() -> int:
    """Return the libpq version psycopg2 is linked against, or 0 when unknown."""
    try:
        from psycopg2 import extensions

        return int(extensions.libpq_version())
    except Exception:  # pragma: no cover - driver missing or odd build
        return 0


def normalize_database_url(url: str) -> str:
    """Return a SQLAlchemy-ready connection URL.

    Managed providers hand out two things SQLAlchemy/psycopg2 choke on:

    * ``postgres://`` — SQLAlchemy 2.x removed this legacy alias.
    * ``channel_binding=require`` — Neon appends it by default, but libpq only
      accepts the keyword from v13. It is dropped on older clients so a pasted
      Neon URL works verbatim instead of failing with
      ``invalid connection option "channel_binding"``.
    """
    url = (url or "").strip()
    if not url:
        return url

    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    parts = urlsplit(url)
    if not parts.scheme.startswith("postgresql"):
        return url

    params = parse_qsl(parts.query, keep_blank_values=True)
    if _libpq_version() < _CHANNEL_BINDING_MIN_LIBPQ:
        params = [(k, v) for k, v in params if k != "channel_binding"]

    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _engine_options(url: str) -> dict:
    """Tuning that keeps connections healthy against a managed/serverless Postgres.

    Neon (and most managed providers) suspend or drop idle connections. Without
    ``pool_pre_ping`` the first request after an idle period raises
    ``OperationalError: server closed the connection unexpectedly``;
    ``pool_recycle`` proactively retires connections before the server does.
    """
    if not url.startswith("postgresql"):
        return {}
    return {
        "pool_pre_ping": True,
        "pool_recycle": _env_int("DB_POOL_RECYCLE", 280),
        "pool_size": _env_int("DB_POOL_SIZE", 5),
        "max_overflow": _env_int("DB_MAX_OVERFLOW", 10),
        "pool_timeout": 30,
        "connect_args": {"connect_timeout": _env_int("DB_CONNECT_TIMEOUT", 10)},
    }


_DATABASE_URL = normalize_database_url(
    os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'jobhunter.db'}")
)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me-in-production")

    SQLALCHEMY_DATABASE_URI = _DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(_DATABASE_URL)

    # Development convenience; production initialises the schema explicitly in
    # docker_entrypoint.py so that concurrent Gunicorn workers cannot race on DDL.
    AUTO_CREATE_DB = True

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # tokens live as long as the session

    # App settings
    JOBS_PER_PAGE = 10
    MATCHES_TOP_N = 12
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB request body cap
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "alerts@jobhunter.local")
    # NOTE: outbound email (alerts, verification) is recorded/logged rather than
    # sent. Wire Flask-Mail + SMTP in worker/celery_app.py for real delivery.

    # Abuse protection for the credential endpoints.
    LOGIN_RATE_LIMIT = _env_int("LOGIN_RATE_LIMIT", 8)
    LOGIN_RATE_WINDOW = _env_int("LOGIN_RATE_WINDOW", 300)

    # Applied to registration and password reset alike, so the two credential
    # flows cannot drift apart.
    MIN_PASSWORD_LENGTH = _env_int("MIN_PASSWORD_LENGTH", 8)

    # The public JSON API re-vectorizes the job corpus on every /api/match call,
    # so it needs its own budget rather than sharing the login limiter.
    API_RATE_LIMIT = _env_int("API_RATE_LIMIT", 30)
    API_RATE_WINDOW = _env_int("API_RATE_WINDOW", 60)

    # Number of trusted upstream proxies; 0 means "not behind a proxy".
    TRUSTED_PROXIES = _env_int("TRUSTED_PROXIES", 0)
    ENABLE_HSTS = False

    # Shared AI gateway (OpenAI-compatible). Ranking stays TF-IDF unless
    # AI_EXPLAIN_MATCHES is turned on; the credential is read from the
    # environment only and is never logged.
    #
    # Both the endpoint and the model names are operator-supplied: the shipped
    # defaults are empty so the project never hardcodes a third-party host or
    # assumes a vendor's model catalogue. `is_configured()` in
    # app/services/ai_gateway.py requires BOTH a base URL and a key, so the
    # feature stays off until an operator deliberately opts in.
    AI_BASE_URL = os.environ.get("AI_BASE_URL", "")
    AI_API_KEY = os.environ.get("AI_API_KEY", "")
    AI_TIMEOUT_SECONDS = _env_int("AI_TIMEOUT_SECONDS", 60)
    AI_MAX_RETRIES = _env_int("AI_MAX_RETRIES", 2)
    AI_MODEL_DEFAULT = os.environ.get("AI_MODEL_DEFAULT", "")
    AI_MODEL_CHAT = os.environ.get("AI_MODEL_CHAT", "")
    AI_MODEL_ANALYZE = os.environ.get("AI_MODEL_ANALYZE", "")
    AI_MODEL_GENERATE = os.environ.get("AI_MODEL_GENERATE", "")
    AI_MODEL_SUMMARIZE = os.environ.get("AI_MODEL_SUMMARIZE", "")
    # Opt-in: adds an LLM written rationale to fit_score(). Off by default so
    # ranking results are byte-for-byte what they were before.
    AI_EXPLAIN_MATCHES = _env_bool("AI_EXPLAIN_MATCHES", False)


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    AUTO_CREATE_DB = False

    # Session hardening. Secure cookies require HTTPS, so this is env-overridable
    # for local HTTP stacks such as `docker compose up` (see docker-compose.yml);
    # leave it on anywhere real users sign in.
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", True)
    REMEMBER_COOKIE_HTTPONLY = True
    PREFERRED_URL_SCHEME = "https"

    # Set TRUSTED_PROXIES=1 when running behind the bundled Nginx / a PaaS router
    # so that url_for(_external=True) and client IPs reflect X-Forwarded-*.
    TRUSTED_PROXIES = _env_int("TRUSTED_PROXIES", 1)

    # HSTS is opt-in: enabling it on a domain you also serve over plain HTTP
    # would lock browsers out.
    ENABLE_HSTS = _env_bool("ENABLE_HSTS", False)


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    # Keep the limiter out of the way of tests that hammer /auth/login.
    LOGIN_RATE_LIMIT = 0


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


class ConfigurationError(RuntimeError):
    """Raised when the environment cannot safely run the selected config."""


def validate_config(app) -> None:
    """Fail fast on misconfiguration instead of booting an insecure server.

    A production deployment that silently falls back to the shipped development
    secret would issue forgeable session cookies, so we stop it at startup.
    """
    if app.testing or app.debug:
        return

    secret = app.config.get("SECRET_KEY") or ""
    if secret in {"", "dev-secret-change-me-in-production", "change-me", "change-me-in-production"}:
        raise ConfigurationError(
            "SECRET_KEY must be set to a unique random value in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if len(secret) < 32:
        raise ConfigurationError("SECRET_KEY must be at least 32 characters in production.")

    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite") and not _env_bool("ALLOW_SQLITE_IN_PRODUCTION", False):
        raise ConfigurationError(
            "Production is configured to use SQLite. Set DATABASE_URL to a PostgreSQL "
            "connection string, or set ALLOW_SQLITE_IN_PRODUCTION=1 to override."
        )
