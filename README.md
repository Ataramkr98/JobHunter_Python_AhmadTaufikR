# JobHunter

**One search across every job portal.**

JobHunter aggregates job listings from multiple Indonesian job boards into a single,
de-duplicated, searchable index. It normalizes messy scraped data into a canonical
taxonomy, collapses the same role appearing on several portals into one result, and
layers candidate tooling on top: saved jobs, an application pipeline, job alerts, a
structured resume builder, and content-based AI job matching.

Built with **Flask + SQLAlchemy 2.x** on the backend and **Jinja2 + Tailwind CSS** on
the front end — server-rendered, SEO-friendly, no client-side framework.

**Live demo:** [job-hunter.taufikr.web.id](https://job-hunter.taufikr.web.id/).
Sign in with `demo@example.com` / `demo12345`, then open
[AI matches](https://job-hunter.taufikr.web.id/resume/matches). The top result and
job detail show a Groq-generated explanation (`openai/gpt-oss-20b`) alongside the
TF-IDF/cosine similarity score. The model explains the ranking without changing it.
See [AI setup and limitations](docs/ai.md).

The public portfolio uses `DEMO_MODE=true` and seeded sample listings. Links on
reserved example domains are displayed as sample sources, without an Apply action.
Real source URLs remain usable. Demo mode labels the workspace and its job counts;
set it to `false` for a live job board.

---

## Table of contents

- [Demo accounts](#demo-accounts)
- [Screenshots](#screenshots)
- [Features](#features)
- [Tech stack](#tech-stack)
- [Architecture](#architecture)
- [Data model](#data-model)
- [Getting started](#getting-started)
- [Frontend build](#frontend-build)
- [Environment variables](#environment-variables)
- [API reference](#api-reference)
- [Testing](#testing)
- [Deployment](#deployment)
- [Engineering notes](#engineering-notes)
- [Scraping legality](#scraping-legality)
- [What is scaffolded vs. shipped](#what-is-scaffolded-vs-shipped)
- [License](#license)

---

## Demo accounts

The seeded dataset includes four accounts, each designed to show a different part of
the product. The **seeker** account is fully populated so no dashboard is ever empty;
the second seeker account is deliberately empty so the first-run and empty states are
visible too. These are the same credentials shown on the sign-in page.

| Role | Email | Password | What it shows |
|---|---|---|---|
| Job seeker (full) | `demo@example.com` | `demo12345` | Complete resume, AI matches, saved jobs, a live application pipeline, 3 alerts |
| Job seeker (empty) | `andi@example.com` | `password123` | Empty states, onboarding flow, resume builder from scratch |
| Employer | `hr@gojek.com` | `password123` | Employer dashboard, 3 postings, applicants with resumes |
| Admin | `admin@jobhunter.local` | `admin123` | Ingestion health, per-source success rates, source toggles |

Rebuild the dataset any time with `python seed.py` (it drops and recreates the schema).

---

## Screenshots

Every image below is generated from the running app by
`npm run screenshots`, against the seeded demo data.

| | |
|---|---|
| ![Landing page](docs/screenshots/01-home.png) | ![Search with filters](docs/screenshots/02-search.png) |
| **Landing page** — live index counters, category browse | **Search** — keyword, location, salary, freshness, remote filters |
| ![Job detail](docs/screenshots/03-job-detail.png) | ![AI matches](docs/screenshots/04-matches.png) |
| **Job detail** — normalized metadata, one provenance link per portal | **AI matches** — TF-IDF ranking with explained skill overlap |
| ![Applications](docs/screenshots/05-applications.png) | ![Employer dashboard](docs/screenshots/06-employer.png) |
| **Application tracker** — pipeline stats and inline stage updates | **Employer dashboard** — postings, applicants, close roles |
| ![Admin](docs/screenshots/07-admin.png) | ![Applicants](docs/screenshots/13-applicants.png) |
| **Admin** — per-source scrape health and toggles | **Applicants** — candidate profiles with resumes, in context |
| ![Saved jobs](docs/screenshots/17-saved.png) | ![Alerts](docs/screenshots/12-alerts.png) |
| **Saved jobs** — a focused shortlist | **Job alerts** — saved searches with pause and delete |
| ![Resume builder](docs/screenshots/16-resume.png) | ![Resume preview](docs/screenshots/18-resume-preview.png) |
| **Resume builder** — structured sections with a completeness meter | **Resume preview** — print-ready sheet generated from that data |
| ![About](docs/screenshots/14-about.png) | ![Login](docs/screenshots/15-login.png) |
| **About** — what the product is and is not | **Login** — with a demo-account hint and password recovery |
| ![404 page](docs/screenshots/09-404.png) | ![Forgot password](docs/screenshots/19-forgot-password.png) |
| **404** — branded error page with search recovery | **Password recovery** — enumeration-safe request and reset |
| ![Mobile](docs/screenshots/08-mobile.png) | ![Tablet](docs/screenshots/11-tablet.png) |
| **Mobile (390px)** — workspace bottom navigation | **Tablet (768px)** — filters collapse, no overflow |

### Responsive verification

| Viewport | Width | Checked |
|---|---|---|
| Desktop wide | 1920px | `docs/screenshots/20-laptop.png` |
| Desktop | 1440px | every screenshot above |
| Tablet | 768px | `docs/screenshots/11-tablet.png` |
| Mobile | 390px | `docs/screenshots/08-mobile.png` |

---

## Features

**Aggregation & search**
- Multi-source ingestion model with per-source health tracking
- **Normalization** — job titles into a canonical taxonomy + seniority, locations into
  city/region + remote flag, salaries into currency/period/min–max, employment type
- **Cross-source de-duplication** — the same role on multiple portals collapses into one
  job that keeps every source link as provenance
- Rich filtering: keyword, location, employment type, category, minimum salary,
  freshness window, remote-only; sort by newest or salary
- Windowed pagination that stays a fixed size no matter how large the index grows

**Candidate workspace**
- Saved jobs and an application tracker with status pipeline (applied → interview →
  offer / rejected)
- Saved-search **job alerts** with instant / daily / weekly cadence and one-click
  unsubscribe
- **Resume builder** with completeness scoring and a print/PDF-ready preview
- **AI job matching** — TF-IDF + cosine similarity ranking with explainable skill
  overlap, plus a per-job fit score on every job page

**Employer portal**
- Employer onboarding, job posting, and applicant review
- Employer-posted jobs are normalized and de-duplicated exactly like scraped jobs, so
  they appear in search and matching with no special-casing

**Platform**
- Free accounts with hashed passwords, CSRF protection on every mutating request
- **Password reset** — request link, set a new password. Single-use, 30-minute expiry,
  SHA-256 digests at rest, and no confirmation of whether an address is registered
- Right-to-erasure account deletion that anonymizes personal data
- Per-endpoint rate limiting on the credential routes *and* the JSON API
- Admin dashboard for ingestion health and source toggles
- Branded error pages, security headers, `robots.txt`, `sitemap.xml`, `/healthz`
- Alembic migrations (`migrations/`) so schema changes are reviewable and reversible

---

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Web framework | Flask 3 (app factory + blueprints) | Small surface area, explicit wiring, easy to test |
| ORM | SQLAlchemy 2.x typed models via Flask-SQLAlchemy | Modern `Mapped[...]` annotations, real type checking |
| Database | SQLite (dev) · PostgreSQL / Neon (prod) | Zero-setup locally, real Postgres in production |
| Auth | Flask-Login + Werkzeug password hashing | Battle-tested, no bespoke crypto |
| Forms | Flask-WTF CSRF | CSRF tokens on every mutating request |
| Templates | Jinja2 | Server-rendered, SEO-friendly |
| Styling | Tailwind CSS 3 + a CSS custom-property design system | Utility classes for layout, design tokens for identity |
| Icons | A generated Lucide SVG sprite (68 symbols) | One icon system, one stroke weight, no emoji, no dead weight |
| Matching | scikit-learn TF-IDF + cosine similarity | Explainable, no GPU, no external model dependency |
| Migrations | Flask-Migrate / Alembic | Reviewable, reversible schema history |
| Async | Celery + Redis | Scheduled scraping and alert evaluation |
| Ingestion | Scrapy + scrapy-playwright | Static and JS-rendered portals |
| Serving | Gunicorn behind Nginx | Standard production shape |
| CI | GitHub Actions | Tests, config guardrails, asset-sync and image-build checks |

---

## Architecture

The app is an application-factory Flask project. **Routes stay thin; business logic
lives in services**, so normalization and matching are unit-testable without a request
context and the search backend can be swapped without touching a single route.

```
Request
   │
   ▼
Blueprints (app/blueprints/)        thin HTTP layer: parse, delegate, respond
   │  main · jobs · accounts · alerts · employer · resume · admin · api
   ▼
Services (app/services/)            business logic, framework-independent
   │  normalization · dedup · search · matching · resume · alerts · ratelimit · urls
   ▼
Models (app/models/)                SQLAlchemy 2.x typed models
   │  job · user · employer
   ▼
Database                            SQLite (dev) · PostgreSQL (prod)
```

```
jobhunter/
├── app/
│   ├── __init__.py            # create_app() factory, error handlers, CLI
│   ├── extensions.py          # db, migrate, login_manager, csrf
│   ├── errors.py              # branded error pages + security headers
│   ├── models/
│   │   ├── job.py             # Source, Company, Job, JobSource, ScrapeRun
│   │   ├── user.py            # User, SavedJob, JobAlert, Application, PasswordResetToken
│   │   └── employer.py        # Employer, PostedJob, Resume
│   ├── services/
│   │   ├── normalization.py   # title/location/salary/type taxonomy
│   │   ├── dedup.py           # dedup hashing + cross-source matching
│   │   ├── search.py          # search backend (SQL now → Meilisearch later)
│   │   ├── matching.py        # TF-IDF + cosine similarity job matching
│   │   ├── resume.py          # resume builder helpers
│   │   ├── alerts.py          # alert scheduling + delivery payloads
│   │   ├── ratelimit.py       # dependency-free rate limiting
│   │   ├── urls.py            # URL safety (XSS + open-redirect guards)
│   │   ├── params.py          # bounded request-parameter parsing
│   │   ├── mail.py            # outbound email (one transport seam)
│   │   └── ai_gateway.py      # optional OpenAI-compatible client
│   ├── blueprints/            # the eight domain blueprints
│   ├── templates/             # Jinja2 + Tailwind
│   └── static/                # compiled CSS, generated icon sprite, self-hosted font
├── migrations/                # Alembic revision history
├── scrapers/                  # Scrapy + scrapy-playwright spiders
├── scripts/
│   ├── build_icon_sprite.py   # regenerates the sprite from template usage
│   └── capture_screenshots.mjs# Playwright capture of docs/screenshots/
├── worker/                    # Celery app + scheduled tasks
├── tests/                     # unittest suite
├── seed.py                    # demo data
├── config.py                  # dev/prod/test config + URL normalization
└── docker-compose.yml         # web · worker · beat · postgres · redis · nginx
```

### Data flow

1. **Ingest** — spiders crawl sources → raw payloads → `NormalizationService` +
   `DedupService` → upsert canonical `Job` rows (one job, many `JobSource` links).
2. **Serve** — Flask serves search/detail/accounts over the canonical store.
   `services/search.py` is a small functional interface, so swapping SQL for
   PostgreSQL FTS or Meilisearch is a one-module change.
3. **Match** — `services/matching.py` vectorizes the active job corpus and a resume with
   TF-IDF and ranks by cosine similarity, reporting the skill overlap that drove it.

---

## Data model

```
Source ──< JobSource >── Job >── Company
  │                       │
  └──< ScrapeRun          └──< SavedJob / Application

User ──< SavedJob
   ├────< JobAlert
   ├────< Application
   ├────< Resume
   ├────< PasswordResetToken
   └──── Employer ──< PostedJob ──> Job
```

`Job` is the canonical, de-duplicated entity. Each occurrence on a portal is a
`JobSource` row, so one job carries many source URLs — that is what makes
"apply on the original portal" work after de-duplication. An employer-posted job also
materialises a canonical `Job` (with `source = "Employer Portal"`), so posted and
scraped jobs are served, filtered, and matched by identical code paths.

---

## Getting started

Requires **Python 3.11+**.

```bash
git clone <your-repo-url>
cd jobhunter

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env               # optional for local SQLite
python seed.py                     # load the demo dataset
python run.py                      # http://127.0.0.1:5000
```

`seed.py` drops and recreates the schema, so it is safe to re-run.

---

## Frontend build

Two generated artifacts are committed so a fresh clone renders correctly without
Node installed. Rebuild them after editing a template or `input.css`:

```bash
npm install
npm run build          # Tailwind CSS + icon sprite
```

| Command | What it does |
|---|---|
| `npm run build:css` | Compiles `app/static/css/input.css` → `app/static/css/app.css` |
| `npm run build:sprite` | Regenerates the Lucide sprite from the icons the templates reference |
| `npm run build:check` | Fails if the committed sprite is stale (used by CI) |
| `npm run screenshots` | Recaptures `docs/screenshots/` from a running dev server |

The sprite is **derived from the templates**, not copied from the icon library. The
previous build shipped all ~1,770 Lucide symbols (477 KB) while the UI referenced
about 60; it is now 68 symbols and ~17 KB. Adding an icon to a template and
re-running the script is the whole workflow, and `--check` fails the build if a
template ever references an icon the sprite does not contain.

Screenshots are captured with Playwright against a live server, so they cannot drift
from the UI:

```bash
python run.py          # in one terminal
npm run screenshots    # in another
```

---

## Environment variables

For Groq setup, visible explanations and matching-score behavior, see [AI matching](docs/ai.md).

Copy `.env.example` to `.env`. Real environment variables always take precedence.

| Variable | Default | Purpose |
|---|---|---|
| `FLASK_CONFIG` | `development` | `development` \| `production` \| `testing` |
| `SECRET_KEY` | dev placeholder | **Required in production.** The app refuses to boot with the default |
| `DATABASE_URL` | SQLite file | PostgreSQL URL. `postgres://` and Neon's `channel_binding` are normalized automatically |
| `DB_POOL_SIZE` | `5` | Connection pool size |
| `DB_MAX_OVERFLOW` | `10` | Connections allowed above the pool size |
| `TRUSTED_PROXIES` | `0` (dev) / `1` (prod) | Trusted upstream proxies for `X-Forwarded-*` |
| `ENABLE_HSTS` | `0` | Enable HSTS once every client is on HTTPS |
| `LOGIN_RATE_LIMIT` | `8` | Max failed logins per client per window (`0` disables) |
| `LOGIN_RATE_WINDOW` | `300` | Rate-limit window in seconds |
| `API_RATE_LIMIT` | `30` | Requests per endpoint per window on `/api/*` |
| `API_RATE_WINDOW` | `60` | API rate-limit window in seconds |
| `MIN_PASSWORD_LENGTH` | `8` | Minimum password length on register and reset |
| `MAIL_DEFAULT_SENDER` | `alerts@jobhunter.local` | From-address for outbound email |
| `REDIS_URL` | — | Broker for the optional Celery worker |
| `MATCHING_BACKEND` | `sklearn` | `stdlib` avoids NumPy/SciPy imports for small corpora on low-memory hosts |
| `AI_BASE_URL` / `AI_API_KEY` | empty | Optional OpenAI-compatible gateway. Both empty ⇒ fully offline |

The `stdlib` matcher keeps English stopwords, unigram/bigram features, smooth
IDF, L2 normalization and cosine scoring. At the 8000-feature cap, tied term
frequencies use lexical order and may select different equal-frequency terms
than NumPy sorting. It is intended for demo corpora; use the default backend
for larger workloads. Tests compare ordinary-corpus scores against sklearn.

Two production guardrails are worth calling out:

- The app **refuses to start** with the development `SECRET_KEY`, or with a SQLite
  database, when `FLASK_CONFIG=production`. Set `ALLOW_SQLITE_IN_PRODUCTION=1` to
  override deliberately. Both paths are asserted in CI.
- `pool_pre_ping` and `pool_recycle` are enabled for PostgreSQL, so a serverless
  database that suspends idle connections (Neon, Supabase) does not surface as
  `server closed the connection unexpectedly` on the first request after a quiet period.

### Security note on credentials

No third-party endpoint or credential is committed anywhere in this repository. The
AI gateway defaults to empty and is only used if **both** `AI_BASE_URL` and
`AI_API_KEY` are set *and* `AI_EXPLAIN_MATCHES=1`; job ranking never needs it. If you
add a real key to `.env` (gitignored) and that file is ever shared, published or
screenshotted, rotate the key — treat it as burned.

---

## API reference

All responses share one envelope:

```jsonc
{ "success": true,  "message": "", "data": { } }
{ "success": false, "message": "...", "data": {}, "error": { } }
```

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/jobs` | Search the index. `q`, `location`, `type`, `category`, `salary_min`, `remote`, `freshness`, `sort`, `page`, `per_page` |
| `GET` | `/api/jobs/<id>` | One job with normalized fields and its source links |
| `GET` | `/api/categories` | Active category facets |
| `POST` | `/api/match` | Rank jobs against a profile. Uses the caller's resume when signed in, or a `profile_text` in the body |

Requests are budgeted per endpoint and per client address. Exceeding the budget
returns `429` with a `Retry-After` header and the standard error envelope:

```jsonc
{ "success": false, "message": "Rate limit exceeded. Try again shortly.",
  "data": {}, "error": { "retry_after_seconds": 42 } }
```

```bash
curl "http://127.0.0.1:5000/api/jobs?q=backend&location=Jakarta&per_page=3"

curl -X POST http://127.0.0.1:5000/api/match \
  -H 'Content-Type: application/json' \
  -d '{"profile_text": "Python Flask PostgreSQL Kubernetes", "skills": ["Python","Kubernetes"], "top_n": 5}'
```

---

## Testing

```bash
python -m unittest discover -v
```

26 tests covering public and authenticated page rendering, role permissions, the
employer application flow, alert scheduling, the full password-reset lifecycle
(hashed single-use tokens, neutral enumeration response, replay rejection), unsubscribe
confirmation, privacy deletion, search and API validation, API and credential rate
limiting, error pages, security headers, sitemap escaping, normalization, matching,
URL-safety guards, and the icon sprite staying in sync with the templates.

CI (`.github/workflows/ci.yml`) additionally asserts that production refuses an
unsafe config, that the icon sprite and compiled CSS are reproducible, and that both
Dockerfiles build.

### Database migrations

Schema changes are Alembic revisions under `migrations/`, not `create_all`:

```bash
export FLASK_APP=run.py

flask db upgrade                          # apply everything pending
flask db migrate -m "add x to y"          # autogenerate a new revision
flask db downgrade                        # roll back one revision
flask db current                          # what is applied right now
```

`create_all` remains available as `flask init-db` for a throwaway local SQLite file,
but it only ever creates *missing* tables — it will silently skip the column changes
a released migration would apply. `docker_entrypoint.py` runs `flask db upgrade` once
before Gunicorn forks; set `SKIP_MIGRATIONS=1` if you apply schema changes out of band.

---

## Deployment

### Render / Railway / Fly.io with Neon

1. Create a free PostgreSQL database at [neon.tech](https://neon.tech) and copy the
   connection string.
2. Create a web service pointing at this repo.
3. Set the environment:

   ```
   FLASK_CONFIG=production
   SECRET_KEY=<64-char random hex>
   DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
   ```

   Generate a secret with
   `python -c "import secrets; print(secrets.token_hex(32))"`.

4. Build: `pip install -r requirements.txt`
5. Start: `gunicorn -w 4 -b 0.0.0.0:$PORT "run:app"`
6. Initialize the schema: `flask db upgrade` (or run `python seed.py` to also load
   the demo dataset — note that `seed.py` drops and recreates every table, so do not
   run it against a database you care about).

### Docker Compose

The bundled stack runs the full production shape — Gunicorn, Celery worker, Celery
beat, PostgreSQL, Redis and Nginx.

```bash
SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") docker compose up --build
# -> http://localhost
```

The web image applies pending migrations on startup. Set a real `SECRET_KEY` (the
stack refuses to boot without one) and remember it serves plain HTTP on `:80`, so it
also sets `SESSION_COOKIE_SECURE=0`; put TLS in front of it and turn that back on for
real users.

### Health check

`GET /healthz` returns `{"status": "ok", "database": "ok"}` (200) or
`{"status": "unhealthy", ...}` (503) when the database is unreachable. Point your
platform's health check at it.

---

## Engineering notes

A few decisions that are easy to get wrong and are handled explicitly here:

- **Cross-source de-duplication is content-based, not URL-based.** `dedup.py` hashes
  the normalized `(company, canonical title, city, remote)` tuple, so "Senior Backend
  Engineer" and "Backend Engineer" at the same company in the same city merge into one
  canonical job while both source links survive as `JobSource` rows.
- **Normalization is a set of pure functions.** Salary parsing handles Indonesian
  conventions (`8,5 jt`, `Rp 8.000.000`, ranges where the unit appears once — `8-12 jt`),
  and taxonomy keywords are matched on word boundaries so "Equipment Operator" does not
  match "Operations".
- **Employer jobs take the same path as scraped jobs.** Posting a job runs it through
  the identical normalize + dedup pipeline and creates a canonical `Job`, so search,
  filters and AI matching need no employer-specific branch.
- **The referrer is never trusted for redirects.** `services/urls.py` validates both
  rendered links (blocks `javascript:`/`data:`) and redirect targets (blocks absolute
  and protocol-relative URLs), so neither an XSS payload nor an open redirect can be
  smuggled through `?next=` or the `Referer` header.
- **Production fails fast.** A default secret key or a SQLite database in production
  stops the boot rather than silently issuing forgeable session cookies.
- **One icon system, generated from usage.** `scripts/build_icon_sprite.py` scans the
  templates for every `icon(...)` call and emits only those symbols, so the sprite
  cannot drift from the UI and cannot silently bloat.
- **Colour comes from tokens, never from a palette name.** Templates use
  `.text-primary` / `.text-muted` / `.surface-inset`, which map to CSS custom
  properties. An earlier version mixed raw Tailwind utilities (`text-slate-500`,
  `text-indigo-600`) with the token system, so re-theming meant hunting every
  utility; that indirection is gone.
- **Secrets are never shipped.** `.env.example` documents every variable with empty
  credential values, and the AI gateway requires an operator to supply both an
  endpoint and a key before it is reachable at all.

---

## Scraping legality

Scraping third-party portals is a **legal gray zone**. Public-data scraping is not
automatically unlawful (*hiQ v. LinkedIn*), but breaching a portal's Terms of Service
and ignoring cease-and-desist letters is real exposure, and Indonesia's **PDP Law
(UU 27/2022)** treats scraping as collection and storage of personal data.

This project follows an ethical-scraping policy: prefer official APIs and feeds, honour
`robots.txt`, rate-limit, attribute and link back to the source, and honour takedowns
within 72 hours. **Get legal counsel before scraping any high-risk source.** The web app
ships with a seeded dataset so it can be evaluated without running a single spider.

---

## What is scaffolded vs. shipped

Stated plainly, so nothing here overclaims:

| Area | Status |
|---|---|
| Web app, search, filters, accounts, password reset, saved jobs, tracker, alerts, resume builder, matching, employer portal, admin | **Fully implemented and tested** |
| Schema history | **Alembic migrations under `migrations/`**; verified to build the full schema from empty on both SQLite and PostgreSQL dialects |
| Security: CSRF, security headers, rate limiting (credentials *and* API), URL-safety guards, enumeration-safe reset, production config validation | **Implemented and tested** |
| Scrapy + scrapy-playwright spiders, Celery worker and beat schedules | **Implemented**, but the shipped dataset is seeded rather than crawled — spiders target third-party portals and are run deliberately, not on boot |
| Outbound email (alerts, password reset) | **Composed and logged, not sent.** One transport function — `app/services/mail.py::_send` — is all that stands between this and real SMTP |
| Search backend | **SQL ILIKE + filters** behind a swappable interface. Meilisearch is the documented upgrade path, not yet wired |
| Rate limiting | **Per worker process.** Move the counters in `services/ratelimit.py` to Redis for a cluster-wide limit; `reset_all()` is the seam |
| AI rationale on job detail | **Off by default** (`AI_EXPLAIN_MATCHES=0`). Ranking is TF-IDF and needs no network call; the gateway client is opt-in and requires operator-supplied credentials |

---

## License

MIT — see [LICENSE](LICENSE).

Bundled third-party assets keep their own licenses: Lucide icons (ISC) and Plus
Jakarta Sans (SIL OFL 1.1).
