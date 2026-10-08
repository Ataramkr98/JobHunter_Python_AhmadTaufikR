"""Centralised HTTP error handling and response hardening.

Every failure path renders the same branded shell instead of Werkzeug's default
white page, and JSON clients (``/api/*``) get a machine-readable body instead of
HTML. Registered from :func:`app.create_app`.
"""
from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

# status -> (title, message, hint)
_ERRORS: dict[int, tuple[str, str, str]] = {
    400: ("That request could not be processed",
          "Some of the submitted details were missing or in the wrong format.",
          "Go back, check the form, and try again."),
    403: ("You do not have access to this page",
          "This area is limited to accounts with the right permissions.",
          "If you think this is a mistake, try logging in with a different account."),
    404: ("We could not find that page",
          "The link may be broken, or the job listing may have been filled and removed.",
          "Try searching the index for something similar."),
    405: ("That action is not supported here",
          "The page was reached with a request the server does not accept.",
          "Return to the previous page and try a different action."),
    413: ("That upload is too large",
          "The request body exceeded the 2 MB limit.",
          "Reduce the size of what you are submitting and try again."),
    429: ("Too many attempts",
          "You have made too many requests in a short period.",
          "Wait a moment, then try again."),
    500: ("Something went wrong on our side",
          "An unexpected error occurred while rendering this page. It has been logged.",
          "Try again in a moment — if it keeps happening, let us know."),
}


def _prefers_json() -> bool:
    """True when the caller is an API client rather than a browser."""
    if request.path.startswith("/api/"):
        return True
    accept = request.accept_mimetypes
    return (
        accept["application/json"] > 0
        and accept["application/json"] >= accept["text/html"]
    )


def _error_response(status: int, *, detail: str | None = None):
    title, message, hint = _ERRORS.get(status, _ERRORS[500])

    if _prefers_json():
        return jsonify({
            "success": False,
            "message": title,
            "error": {"status": status, "detail": detail or message},
            "data": {},
        }), status

    return render_template(
        "errors/error.html",
        status=status,
        title=title,
        message=message,
        hint=hint,
        detail=detail,
    ), status


def _make_handler(status: int):
    def handler(error):
        detail = None
        # Surface the specific validation message for 4xx (e.g. CSRF failure)
        # without leaking internals on a 5xx.
        if status < 500 and isinstance(error, HTTPException) and error.description:
            description = str(error.description)
            if description and not description.startswith(("The requested URL", "You don't have")):
                detail = description
        return _error_response(status, detail=detail)

    handler.__name__ = f"handle_{status}"
    return handler


def register_error_handlers(app: Flask) -> None:
    for status in _ERRORS:
        app.register_error_handler(status, _make_handler(status))

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - exercised via 500 page
        # HTTPExceptions are already routed to the handlers above; anything that
        # reaches here is a genuine bug, so log it with a traceback.
        if isinstance(error, HTTPException):
            return _make_handler(error.code or 500)(error)
        app.logger.exception("Unhandled exception on %s", request.path)
        return _error_response(500)


def register_security_headers(app: Flask) -> None:
    """Attach hardening headers to every response.

    The CSP allows the inline styles the templates already use and the bundled
    font, but blocks everything else — there is no third-party JavaScript in this
    app, so the policy can stay tight.
    """

    @app.after_request
    def _apply(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'",
        )
        if app.config.get("ENABLE_HSTS"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
