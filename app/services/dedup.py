"""Deduplication service (FR-B5/B6): two-tier matching.

1. Exact source dedup  -> unique(source_id, external_id) at the DB layer.
2. Cross-source dedup  -> a dedup_hash over normalized (company, canonical title,
   seniority, city/remote); matching jobs merge into one canonical Job with many
   sources.

Seniority is part of the key deliberately. Without it, "Backend Engineer Intern",
"Backend Engineer", "Senior Backend Engineer" and "Lead Backend Engineer" at the same
company all reduce to the same canonical title and therefore the same hash — so a
brand-new intern posting would silently merge into the senior listing and disappear
from the index. A merge this aggressive destroys real, distinct jobs, so the hash
keeps the one field that separates them.
"""
import hashlib
import re

from app.services.normalization import normalize_title, normalize_location


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def dedup_hash(company: str, title: str, location: str, is_remote: bool = False) -> str:
    canonical, seniority = normalize_title(title)
    loc = normalize_location(location) if location else {"city": "", "is_remote": is_remote}
    remote = bool(loc.get("is_remote", is_remote))
    key = f"{_norm(company)}|{_norm(canonical)}|{_norm(seniority)}|{_norm(loc.get('city', ''))}|{remote}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def find_matching_job(company: str, title: str, location: str, is_remote: bool = False):
    """Return (existing_job_or_None, hash) for an active job with the same dedup key."""
    from app.models.job import Job
    h = dedup_hash(company, title, location, is_remote)
    existing = Job.query.filter_by(dedup_hash=h, status="active").first()
    return existing, h
