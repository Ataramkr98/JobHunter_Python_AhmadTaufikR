"""AI matching (Phase 2) — content-based matching with TF-IDF + cosine similarity.

No GPU / external model required: we vectorize the active job corpus and the
candidate's profile text, then rank jobs by cosine similarity. Skill overlap is
reported alongside the score for an explainable "why this matched" signal.

Scaling note
------------
The corpus is vectorized per request, which is deliberately simple and fast at the
current index size (tens to low thousands of jobs, single-digit milliseconds). It
is *not* the right shape for a six-figure index: at that point, fit the vectorizer
once per corpus version (cache keyed on row count + max ``updated_at``), or move
ranking to a dedicated search engine (Meilisearch / pgvector) behind the same
``match_jobs`` / ``fit_score`` signatures. The call sites would not change.
"""
import json

from flask import current_app, has_app_context

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.models.job import Job


def _ai_explanation_enabled() -> bool:
    """True only when the operator opted in *and* the credential is present."""
    from app.services.ai_gateway import is_configured

    return (
        has_app_context()
        and bool(current_app.config.get("AI_EXPLAIN_MATCHES"))
        and is_configured()
    )


def _explain_fit(profile_text: str, job, breakdown: dict) -> str | None:
    """Ask the gateway for a short written rationale. Never raises."""
    from app.services.ai_gateway import chat_json

    try:
        data = chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You explain job-candidate fit. Use only the supplied "
                        "data, be concrete, and never invent facts. Answer in the "
                        "same language as the job description. Return JSON with a "
                        "single key 'explanation' of at most 60 words."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "score": breakdown.get("score"),
                            "matched_skills": breakdown.get("matched_skills"),
                            "missing_skills": breakdown.get("missing_skills"),
                            "job_text": job.search_text()[:3000],
                            "profile_text": profile_text[:3000],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            feature="ANALYZE",
        )
    except Exception:  # noqa: BLE001 - an explanation is optional, never fatal
        return None
    text = data.get("explanation")
    return str(text)[:600] if text else None


def resume_to_profile_text(resume) -> str:
    """Flatten a Resume into a single text blob for vectorization."""
    if resume is None:
        return ""
    parts = [resume.headline or "", resume.summary or "", " ".join(resume.skills or [])]
    for exp in (resume.experiences or []):
        parts.append(f"{exp.get('role', '')} {exp.get('company', '')} {exp.get('description', '')}")
    for edu in (resume.educations or []):
        parts.append(f"{edu.get('degree', '')} {edu.get('school', '')}")
    return " ".join(p for p in parts if p)


def _skill_set(skills) -> set[str]:
    if isinstance(skills, str):
        skills = skills.replace("\n", ",").split(",")
    return {str(s).strip().lower() for s in (skills or []) if s and str(s).strip()}


def match_jobs(profile_text: str, top_n: int = 12, profile_skills=None,
               category: str | None = None, city: str | None = None) -> list[dict]:
    """Rank active jobs against a profile text. Returns list of
    {job, score (0-100), matched_skills, missing_skills}."""
    query = Job.query.filter_by(status="active")
    if category:
        query = query.filter(Job.category == category)
    if city:
        query = query.filter(Job.city.ilike(f"%{city}%"))
    jobs = query.all()
    if not jobs or not isinstance(profile_text, str) or not profile_text.strip():
        return []

    try:
        top_n = min(100, max(1, int(top_n)))
    except (TypeError, ValueError):
        top_n = 12

    corpus = [j.search_text() for j in jobs]
    vectorizer = TfidfVectorizer(stop_words="english", max_features=8000, ngram_range=(1, 2))
    try:
        X = vectorizer.fit_transform(corpus)
        profile_vec = vectorizer.transform([profile_text])
    except ValueError:
        # Empty/stop-word-only job corpora should produce no matches, not a 500.
        return []
    scores = cosine_similarity(profile_vec, X).flatten()

    want = _skill_set(profile_skills)
    ranked = sorted(zip(jobs, scores), key=lambda t: t[1], reverse=True)

    results = []
    for job, score in ranked:
        if len(results) >= top_n:
            break
        have = _skill_set(job.skills)
        matched = sorted(want & have)
        missing = sorted(have - want)
        results.append({
            "job": job,
            "score": round(float(score) * 100, 1),
            "matched_skills": matched,
            "missing_skills": missing[:6],
        })
    return results


def fit_score(profile_text: str, profile_skills, job) -> dict:
    """Fit breakdown for a single job (used on the job detail page)."""
    if not isinstance(profile_text, str) or not profile_text.strip():
        return {"score": 0, "matched_skills": [], "missing_skills": []}
    vectorizer = TfidfVectorizer(stop_words="english", max_features=8000, ngram_range=(1, 2))
    docs = [job.search_text(), profile_text]
    try:
        X = vectorizer.fit_transform(docs)
        score = float(cosine_similarity(X[0:1], X[1:2])[0, 0])
    except ValueError:
        score = 0.0
    want = _skill_set(profile_skills)
    have = _skill_set(job.skills)
    breakdown = {
        "score": round(score * 100, 1),
        "matched_skills": sorted(want & have),
        "missing_skills": sorted(have - want)[:8],
    }
    if _ai_explanation_enabled():
        breakdown["ai_explanation"] = _explain_fit(profile_text, job, breakdown)
    return breakdown
