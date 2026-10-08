"""Normalization services (FR-B): turn messy scraped fields into canonical form.

Pure functions — easy to unit test, reused by both the ingestion pipeline and
the employer "post a job" flow so employer jobs normalize exactly like scraped ones.
"""
import re

# --------------------------------------------------------------------------- #
# Title taxonomy
# --------------------------------------------------------------------------- #
TITLE_FAMILIES = [
    ("Backend Engineer", ["backend", "back end", "back-end", "server side", "api engineer"]),
    ("Frontend Engineer", ["frontend", "front end", "front-end", "ui engineer", "web developer"]),
    ("Fullstack Engineer", ["fullstack", "full stack", "full-stack"]),
    ("Mobile Engineer", ["android", "ios", "mobile", "flutter", "react native"]),
    ("Software Engineer", ["software engineer", "software developer", "swe", "programmer", "application developer"]),
    ("DevOps Engineer", ["devops", "dev ops", "site reliability", "sre", "platform engineer", "infrastructure"]),
    ("Data Engineer", ["data engineer", "etl", "data platform", "data infrastructure"]),
    ("Data Scientist", ["data scientist", "machine learning", "ml engineer", "ai engineer", "data science"]),
    ("Data Analyst", ["data analyst", "business intelligence", "bi analyst", "analytics"]),
    ("QA Engineer", ["qa", "quality assurance", "test engineer", "tester", "sdet"]),
    ("Security Engineer", ["security", "secops", "cybersecurity", "infosec"]),
    ("Product Manager", ["product manager", "product owner", "pm"]),
    ("Project Manager", ["project manager", "scrum master", "delivery manager"]),
    ("Product Designer", ["product designer", "ux designer", "ui/ux", "ux/ui", "interaction designer"]),
    ("UI/UX Designer", ["ui designer", "graphic designer", "visual designer", "designer"]),
    ("Business Analyst", ["business analyst", "ba "]),
    ("Marketing", ["marketing", "growth", "seo", "sem", "content", "social media", "brand"]),
    ("Sales", ["sales", "account executive", "business development", "bd ", "salesforce"]),
    ("Finance", ["finance", "accountant", "accounting", "financial", "treasury", "tax"]),
    ("Human Resources", ["hr", "human resource", "recruiter", "talent", "people ops", "hrd"]),
    ("Operations", ["operations", "ops", "supply chain", "logistics", "warehouse", "admin"]),
    ("Customer Support", ["customer support", "customer service", "cs ", "support specialist", "call center"]),
]

_SENIORITY_RULES = [
    ("intern", ["intern", "internship", "magang", "trainee", "apprentice"]),
    ("junior", ["junior", "jr", "entry", "entry-level", "fresh graduate", "fresh grad", "graduate", "associate"]),
    ("lead", ["lead", "principal", "staff", "head of", "director", "vp", "chief", "manager", "architect"]),
    ("senior", ["senior", "sr", "sr.", "experienced"]),
]


def _contains_keyword(text: str, keyword: str) -> bool:
    """Match taxonomy keywords without letting short tokens match inside words."""
    keyword = keyword.strip()
    if not keyword:
        return False
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text) is not None


def normalize_title(title: str) -> tuple[str, str]:
    """Return (canonical_title, seniority)."""
    if not title:
        return ("Other", "unknown")
    t = str(title).lower()

    seniority = "mid"
    for level, kws in _SENIORITY_RULES:
        if any(_contains_keyword(t, k) for k in kws):
            seniority = level
            break

    for canonical, kws in TITLE_FAMILIES:
        if any(_contains_keyword(t, k) for k in kws):
            return (canonical, seniority)
    return ("Other", seniority)


# --------------------------------------------------------------------------- #
# Location
# --------------------------------------------------------------------------- #
_REMOTE_KW = ["remote", "wfh", "work from home", "work-from-home", "remote-first", "anywhere"]

_ID_CITIES = {
    "jakarta": ("Jakarta", "DKI Jakarta"),
    "bandung": ("Bandung", "West Java"),
    "surabaya": ("Surabaya", "East Java"),
    "yogyakarta": ("Yogyakarta", "DI Yogyakarta"),
    "jogja": ("Yogyakarta", "DI Yogyakarta"),
    "semarang": ("Semarang", "Central Java"),
    "tangerang": ("Tangerang", "Banten"),
    "bekasi": ("Bekasi", "West Java"),
    "depok": ("Depok", "West Java"),
    "bogor": ("Bogor", "West Java"),
    "medan": ("Medan", "North Sumatra"),
    "denpasar": ("Denpasar", "Bali"),
    "bali": ("Denpasar", "Bali"),
    "makassar": ("Makassar", "South Sulawesi"),
    "palembang": ("Palembang", "South Sumatra"),
    "batam": ("Batam", "Riau Islands"),
    "balikpapan": ("Balikpapan", "East Kalimantan"),
    "singapore": ("Singapore", "Singapore"),
}


def normalize_location(raw: str) -> dict:
    """Return {city, region, country, is_remote}."""
    out = {"city": "", "region": "", "country": "Indonesia", "is_remote": False}
    if not raw:
        return out
    raw = str(raw)
    loc = raw.lower()
    out["is_remote"] = any(k in loc for k in _REMOTE_KW)
    for key, (city, region) in _ID_CITIES.items():
        if key in loc:
            out["city"] = city
            out["region"] = region
            if key == "singapore":
                out["country"] = "Singapore"
            break
    if not out["city"]:
        cleaned = raw.split(",")[0].strip().title()
        if cleaned.lower() not in _REMOTE_KW:
            out["city"] = cleaned
    return out


# --------------------------------------------------------------------------- #
# Salary
# --------------------------------------------------------------------------- #
_NUM = re.compile(r"(\d+(?:[.,]\d+)?)\s*(jt|juta|k|rb|ribu|miliar|billion|million|m)?\b", re.I)
_SUFFIX = {
    "jt": 1e6, "juta": 1e6, "million": 1e6,
    "k": 1e3, "rb": 1e3, "ribu": 1e3,
    "m": 1e9, "miliar": 1e9, "billion": 1e9,
}


def _collapse_thousands(s: str) -> str:
    """Collapse grouped thousands while preserving decimal commas/dots."""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"(\d)[.,](\d{3})(?=\D|$)", r"\1\2", s)
    return s


def normalize_salary(text: str) -> dict:
    result = {"min": None, "max": None, "currency": "IDR", "period": "month"}
    if not text:
        return result
    t = str(text).lower()

    if any(c in t for c in ["usd", "$"]):
        result["currency"] = "USD"
    elif "sgd" in t:
        result["currency"] = "SGD"
    elif "eur" in t or "€" in t:
        result["currency"] = "EUR"

    if re.search(r"(tahun|year|annual|yearly)", t):
        result["period"] = "year"
    elif re.search(r"(hari|day|daily)", t):
        result["period"] = "day"
    elif re.search(r"(jam|hour|hourly)", t):
        result["period"] = "hour"

    # Indonesian decimals commonly use a comma ("8,5 jt"); commas with exactly
    # three following digits are treated as grouping separators instead.
    t2 = _collapse_thousands(t).replace(",", ".")
    parsed_nums = []
    for m in _NUM.finditer(t2):
        tok, suf = m.group(1), m.group(2)
        try:
            val = float(tok)
            if val > 0:
                parsed_nums.append((val, suf.lower() if suf else None))
        except ValueError:
            continue
    # Ranges often put the unit only once: "8-12 jt". Propagate the shared
    # suffix so the first bound is not accidentally stored as IDR 8.
    suffixes = {suffix for _, suffix in parsed_nums[:2] if suffix}
    shared_suffix = next(iter(suffixes)) if len(suffixes) == 1 else None
    nums = [
        value * _SUFFIX[suffix or shared_suffix] if (suffix or shared_suffix) else value
        for value, suffix in parsed_nums
    ]
    if len(nums) >= 2:
        result["min"], result["max"] = min(nums[:2]), max(nums[:2])
    elif len(nums) == 1:
        if re.search(r"(up to|maximum|max\.?|hingga|sampai)", t):
            result["max"] = nums[0]
        else:
            result["min"] = nums[0]
    return result


# --------------------------------------------------------------------------- #
# Employment type (robust to "Full-time", "full_time", "fulltime", "tetap", ...)
# --------------------------------------------------------------------------- #
def normalize_employment_type(text: str) -> str:
    if not text:
        return "unknown"
    t = str(text).lower().replace("_", " ").replace("-", " ")
    if any(k in t for k in ["intern", "magang", "internship"]):
        return "intern"
    if any(k in t for k in ["part time", "parttime", "paruh waktu"]):
        return "part_time"
    if any(k in t for k in ["contract", "kontrak", "freelance", "contractor", "temporary"]):
        return "contract"
    if any(k in t for k in ["full time", "fulltime", "permanent", "tetap"]):
        return "full_time"
    return "full_time"


# --------------------------------------------------------------------------- #
# Category
# --------------------------------------------------------------------------- #
_CATEGORY_BY_TITLE = {
    "Engineering": ["Backend Engineer", "Frontend Engineer", "Fullstack Engineer", "Mobile Engineer",
                    "Software Engineer", "DevOps Engineer", "QA Engineer", "Security Engineer"],
    "Data": ["Data Engineer", "Data Scientist", "Data Analyst"],
    "Design": ["Product Designer", "UI/UX Designer"],
    "Product": ["Product Manager", "Project Manager", "Business Analyst"],
    "Marketing": ["Marketing"],
    "Sales": ["Sales"],
    "Finance": ["Finance"],
    "Human Resources": ["Human Resources"],
    "Operations": ["Operations"],
    "Customer Support": ["Customer Support"],
}


def normalize_category(canonical_title: str) -> str:
    for category, titles in _CATEGORY_BY_TITLE.items():
        if canonical_title in titles:
            return category
    return "Other"


def normalize_job(raw: dict) -> dict:
    """Normalize a raw scraped/posted dict into canonical job fields."""
    title = str(raw.get("title") or "").strip()
    location = str(raw.get("location") or "").strip()
    description = str(raw.get("description") or "").strip()
    canonical, seniority = normalize_title(title)
    loc = normalize_location(location)
    salary = normalize_salary(raw.get("salary", ""))
    etype = normalize_employment_type(raw.get("employment_type", ""))
    skills = raw.get("skills", []) or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.replace("\n", ",").split(",") if s.strip()]
    else:
        skills = [str(s).strip() for s in skills if s is not None and str(s).strip()]
    return {
        "title": title,
        "canonical_title": canonical,
        "seniority": seniority,
        "description": description,
        "location_raw": location,
        "city": loc["city"],
        "region": loc["region"],
        "country": loc["country"],
        "is_remote": loc["is_remote"],
        "salary_min": salary["min"],
        "salary_max": salary["max"],
        "salary_currency": salary["currency"],
        "salary_period": salary["period"],
        "employment_type": etype,
        "category": normalize_category(canonical),
        "skills": skills,
    }
