"""Resume builder helpers (Phase 2)."""
from app.services.urls import safe_web_url  # noqa: F401  (re-exported for existing callers)

__all__ = [
    "safe_web_url", "completeness", "parse_list",
    "parse_experiences", "parse_educations",
]


def completeness(resume) -> tuple[int, list[tuple[str, bool]]]:
    """Return (percent_complete, [(label, filled?), ...])."""
    checks = [
        ("Full name", bool(resume.full_name)),
        ("Headline", bool(resume.headline)),
        ("Contact email", bool(resume.email)),
        ("Location", bool(resume.location)),
        ("Professional summary", bool(resume.summary)),
        ("Skills", bool(resume.skills)),
        ("Work experience", bool(resume.experiences)),
        ("Education", bool(resume.educations)),
    ]
    filled = sum(1 for _, ok in checks if ok)
    return int(filled / len(checks) * 100), checks


def parse_list(raw: str) -> list[str]:
    """Parse a comma/newline separated string into a clean list."""
    if not raw:
        return []
    parts = raw.replace("\n", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def parse_experiences(roles, companies, starts, ends, descriptions) -> list[dict]:
    """Zip parallel form arrays into a list of experience dicts (drop empty rows)."""
    out = []
    for i in range(len(roles)):
        role = (roles[i] or "").strip()
        if not role:
            continue
        out.append({
            "role": role,
            "company": (companies[i] or "").strip() if i < len(companies) else "",
            "start": (starts[i] or "").strip() if i < len(starts) else "",
            "end": (ends[i] or "").strip() if i < len(ends) else "",
            "description": (descriptions[i] or "").strip() if i < len(descriptions) else "",
        })
    return out


def parse_educations(degrees, schools, years) -> list[dict]:
    out = []
    for i in range(len(degrees)):
        degree = (degrees[i] or "").strip()
        if not degree:
            continue
        out.append({
            "degree": degree,
            "school": (schools[i] or "").strip() if i < len(schools) else "",
            "year": (years[i] or "").strip() if i < len(years) else "",
        })
    return out
