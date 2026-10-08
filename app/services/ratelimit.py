"""Rate limiting for the credential endpoints.

Deliberately dependency-free: this guards ``/auth/login`` and ``/auth/register``
against brute force and credential stuffing without requiring Redis to be
deployed alongside a small portfolio app.

The counter lives in the worker process, so the effective limit scales with the
number of Gunicorn workers. That is an accepted trade-off here — swap ``_HITS``
for a Redis ``INCR``/``EXPIRE`` pair to make it cluster-wide; nothing outside
this module needs to change.
"""
import threading
import time
from collections import deque

_MAX_TRACKED_KEYS = 10_000

_HITS: dict[str, deque[float]] = {}
_LOCK = threading.Lock()


def _prune(bucket: deque[float], window: float, now: float) -> None:
    cutoff = now - window
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()


def _evict_stale(now: float, window: float) -> None:
    """Drop buckets that have gone quiet so memory stays bounded."""
    for key in [k for k, v in _HITS.items() if not v or v[-1] <= now - window]:
        _HITS.pop(key, None)


def hit_count(key: str, window: float) -> int:
    """Return the number of recorded hits for ``key`` inside ``window`` seconds."""
    now = time.monotonic()
    with _LOCK:
        bucket = _HITS.get(key)
        if not bucket:
            return 0
        _prune(bucket, window, now)
        return len(bucket)


def register_hit(key: str, window: float) -> int:
    """Record a hit and return the new count within the window."""
    now = time.monotonic()
    with _LOCK:
        if len(_HITS) > _MAX_TRACKED_KEYS:
            _evict_stale(now, window)
        bucket = _HITS.setdefault(key, deque())
        _prune(bucket, window, now)
        bucket.append(now)
        return len(bucket)


def reset(key: str) -> None:
    """Clear the counter for ``key`` (called after a successful login)."""
    with _LOCK:
        _HITS.pop(key, None)


def reset_all() -> None:
    """Drop every counter.

    The counters are process-global, so tests need a way to start from a known
    state without depending on the order unittest happens to run them in. Also
    the sane response to an operator wanting to clear a limit after unblocking
    a locked-out user.
    """
    with _LOCK:
        _HITS.clear()


def seconds_until_retry(key: str, window: float) -> int:
    """Seconds the caller should wait before the oldest hit ages out."""
    now = time.monotonic()
    with _LOCK:
        bucket = _HITS.get(key)
        if not bucket:
            return 0
        _prune(bucket, window, now)
        if not bucket:
            return 0
        return max(1, int(window - (now - bucket[0])) + 1)
