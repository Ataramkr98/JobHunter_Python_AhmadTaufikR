"""URL safety helpers.

Two different problems, two different guards:

* :func:`safe_web_url` — user-supplied links that we render as ``href``. Blocks
  ``javascript:``/``data:`` payloads that would otherwise be XSS vectors.
* :func:`safe_local_path` — redirect targets taken from ``?next=`` or the
  ``Referer`` header. Blocks absolute and protocol-relative URLs so the app
  cannot be used as an open redirect.
"""
from urllib.parse import urlsplit


def safe_web_url(raw: str) -> str:
    """Normalize an ordinary web URL, discarding unsafe schemes.

    ``example.com`` becomes ``https://example.com``; ``javascript:alert(1)``
    and ``data:...`` become an empty string.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    initial = urlsplit(value)
    if initial.scheme and initial.scheme not in {"http", "https"}:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return value


def safe_local_path(target: str | None, fallback: str = "/") -> str:
    """Return ``target`` only when it is a same-origin absolute path.

    Rejects protocol-relative (``//evil.com``), absolute (``https://evil.com``),
    backslash-smuggled (``/\\evil.com``) and CR/LF-injected values, falling back
    to ``fallback`` otherwise.
    """
    if not target or not isinstance(target, str):
        return fallback
    if "\r" in target or "\n" in target or "\\" in target:
        return fallback
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return fallback
    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return fallback
    return target
