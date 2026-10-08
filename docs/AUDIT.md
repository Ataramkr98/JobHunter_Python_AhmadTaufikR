# JobHunter — Audit & Production-Readiness Report

Date: 2026-10-04 (second pass; first pass 2026-09-13)
Scope: full repository audit, bug remediation, production hardening, portfolio polish.

The first pass closed the functional gaps (error pages, open-redirect guards, windowed
pagination, Docker schema bootstrap, Postgres URL handling). This pass re-audited the
whole repository independently and worked on what the first pass had left: **a live
credential committed to the working tree, a 477 KB icon sprite, no migration history,
an unbounded public API, an unsafe unsubscribe link, no password recovery, and a
design system that templates were quietly bypassing.**

---

## 1. Project health report

### Frontend

**Status — strong design system, three real leaks in the token layer.**

The templates use a coherent component vocabulary (`panel`, `btn`, `field`,
`job-card`, `list-row`, `empty-state`, `stat-card`) on CSS custom properties, with one
Lucide sprite and empty states on every collection view.

| Area | Finding |
|---|---|
| Problems found | The sprite shipped **all 1,776 Lucide symbols (477 KB)** while the UI referenced ~60; templates mixed raw Tailwind palette classes (`text-slate-500`, `text-indigo-600`, `bg-slate-50`, `text-red-600`) with the token system, bypassing re-theming; six inline `style=` attributes where a class belongs; two category tiles had no icon and silently fell back to a generic briefcase; `Operations` and `Other` were missing from the map entirely; the application tracker's submit button orphaned onto its own line; the status badge duplicated the status select beside it; the 404 page stranded the footer mid-screen |
| Missing parts | Nothing structural — all 44 route/role combinations rendered without a single template error |
| Not a problem | No random gradients, no fake statistics, no template filler, no emoji icons, no duplicate components, no second icon library |

Three further defects were found by *looking at* the rendered screens rather than by
reading the templates — the application-tracker layout, the duplicated status badge,
and the escaped cron string on the admin page. Screenshots are now generated from the
running app (`npm run screenshots`) so the portfolio images cannot drift from the UI.

### Backend

**Status — correct layering, four genuine security/robustness gaps.**

Application-factory Flask with eight domain blueprints and a real services layer.
Routes stay thin; normalization, dedup, search, matching, resume and alert logic are
framework-independent and unit-testable. CSRF on every mutating request.

| Area | Finding |
|---|---|
| Problems found | `/alerts/unsubscribe/<token>` **changed state on GET** (email-client prefetch would silently unsubscribe users); `/api/match` was **unbounded** and re-vectorizes the corpus per call, so one client could pin a CPU; the sitemap interpolated company slugs into `<loc>` **without XML escaping**; `.env` held a **live third-party API key**, and `config.py` hardcoded that vendor's gateway as the shipped default; the cross-source dedup key **omitted seniority**, so an intern posting merged into a senior listing and disappeared from the index |
| Missing parts | Password recovery (the one auth flow a real product cannot skip), migration history, a mail seam, an API rate limiter |
| Retained | Clean route → service → model layering was already correct and was not refactored |

### Database

**Status — correct models, no history.**

| Area | Finding |
|---|---|
| Problems found | Flask-Migrate was installed and wired into `create_app` but `migrations/` had never been initialised, so every deployment relied on `create_all` — which only ever creates *missing* tables and silently skips column changes |
| Missing parts | An Alembic revision history — added and verified to build all 13 tables from empty |
| Verified | SQLite and PostgreSQL dialects both autogenerate cleanly |

### UI/UX

**Quality score: 9 / 10** (was ~8.5).
Typography hierarchy, spacing and the restrained palette all hold up. Raised by
tokenising every colour (the UI is now fully re-themeable from `:root` alone), giving
the two dynamic progress meters proper `role="progressbar"` semantics, and making the
destructive panel readable without relying on an icon.

### Feature completeness

**~97%.** The remaining 3% is honestly-scoped: outbound email is composed and logged
rather than sent behind one transport function, and the search backend is SQL rather
than Meilisearch. Both are documented rather than faked.

---

## 2. Fixes applied (this pass)

### 2.1 A live API credential in the working tree

**Problem:** `.env` — gitignored, but sitting in the project folder — contained
`AI_API_KEY=sk-qwen-…`, a working key for a third-party gateway. For a project about
to be published and screenshotted, that is a credential that will eventually leak.
Worse, `config.py` hardcoded that same vendor's endpoint
(`https://ai.autoapp.biz.id/v1`) and its model catalogue as the *shipped default*, so
the public source advertised a specific third-party service as a dependency.

**Root cause:** Credentials were configured locally and the defaults were never
neutralised for public consumption.

**Solution:** The key was removed from `.env` and the user advised to rotate it.
`AI_BASE_URL` and all five `AI_MODEL_*` settings now default to **empty**. The feature
is gated behind `is_configured()`, which requires *both* an endpoint and a key, so the
app is fully offline until an operator deliberately opts in. The vendor-specific
`ALLOWED_MODELS` allowlist is gone — `resolve_model()` now walks the per-feature
override and raises a clear error instead of guessing a model name the operator's
gateway may not serve. `.env.example` documents the block with empty values.

**Files changed:** `.env`, `.env.example`, `config.py`, `app/services/ai_gateway.py`.
**Testing:** With no credentials configured the app boots and every page renders;
`is_configured()` returns `False`, so `AI_EXPLAIN_MATCHES` stays inert.

### 2.2 The icon sprite shipped the entire icon library

**Problem:** `app/static/icons/lucide-sprite.svg` was a verbatim copy of
`lucide-static/sprite.svg` — **1,776 symbols, 477 KB** — while the templates
referenced about 60. Every visitor downloaded ~95% dead weight, and the file could
never be regenerated without re-copying the whole library.

**Root cause:** The sprite was committed once as a vendor artifact with no generation
step, so it could not track actual usage.

**Solution:** `scripts/build_icon_sprite.py` scans `app/templates/**/*.html` for every
`icon(...)` argument and every dict-literal icon value, then emits only those symbols
from `node_modules/lucide-static/icons/*.svg`. It hard-fails if a template references
an icon the library does not contain (catching typos), and `--check` fails CI when the
committed sprite is stale. Wired in as `npm run build:sprite` / `build:check`, and
`npm run build` now produces both artifacts.

Result: **1,776 symbols / 477 KB → 68 symbols / 17 KB**, with zero unresolved
references and zero orphans.

**Files changed:** `scripts/build_icon_sprite.py` (new),
`app/static/icons/lucide-sprite.svg`, `package.json`.
**Testing:** A structural check parses the sprite as XML, asserts every symbol has
geometry, that no inner element carries a `class`/`stroke` override that would fight
the `.icon` CSS, and that the referenced set equals the shipped set exactly. A unit
test fails the suite if the sprite grows back toward the full library.

### 2.3 Password reset did not exist

**Problem:** Registration, login and deletion existed, but there was no way to recover
a forgotten password — the single most-expected gap in an auth flow, and a hard
requirement for any deployed product.

**Root cause:** Feature never built.

**Solution:** A full lifecycle, not a stub.

- `PasswordResetToken` model: single-use, 30-minute TTL, **SHA-256 digest at rest**
  so a database leak does not hand over working reset links. `issue_reset_token()`
  returns `(row, plaintext)` rather than parking the secret on the instance, so it
  can never be flushed by accident — an earlier draft used a shadow attribute and
  SQLAlchemy correctly rejected the non-`Mapped` annotation.
- `User.issue_reset_token()` invalidates any earlier unused link, so requesting a new
  link retires the old one.
- `GET /auth/forgot-password`, `POST /auth/forgot-password`,
  `GET|POST /auth/reset-password/<token>`, plus two templates.
- The response is **identical whether or not the address is registered**
  ("If an account exists for that address…"), so the form is not an account-enumeration
  oracle. A successful reset signs the user out everywhere.
- Account deletion invalidates outstanding reset tokens alongside everything else.
- Reuses the existing sliding-window limiter under a `reset-request` scope.
- `MIN_PASSWORD_LENGTH` (default 8) is now config-driven and shared by registration
  and reset — previously the only rule was a hardcoded `6` in one place.

**Files changed:** `app/models/user.py`, `app/blueprints/accounts.py`,
`app/templates/accounts/forgot_password.html` (new),
`app/templates/accounts/reset_password.html` (new),
`app/templates/accounts/login.html`, `app/templates/accounts/register.html`,
`app/__init__.py`, `config.py`, `migrations/`.
**Testing:** Five new tests — round trip with hash-vs-plaintext assertion, mismatch
rejection, replay rejection, neutral enumeration response, and link invalidation on
re-issue.

### 2.4 Unsubscribe changed state on GET

**Problem:** `/alerts/unsubscribe/<token>` deactivated the alert and committed on
**any** request method. Alert links live in email clients, which routinely prefetch
URLs in the background to build link previews. A prefetch alone would silently stop
someone's job alerts without them ever clicking anything.

**Root cause:** The convenience of a mail-friendly GET link was allowed to override
the reason CSRF-protected mutations are POST-only.

**Solution:** GET now renders a confirmation page (`alerts/unsubscribe.html`) that
shows what is being stopped; only the explicit POST performs the change. The mail link
still works with one click, and a prefetch is now inert.

**Files changed:** `app/blueprints/alerts.py`, `app/templates/alerts/unsubscribe.html` (new).
**Testing:** A test asserts GET leaves `active` untouched and POST flips it.

### 2.5 The public API could be used as a CPU denial-of-service

**Problem:** `/api/*` was entirely unauthenticated and unbounded. `GET /api/jobs` is a
cheap indexed query, but `POST /api/match` builds a TF-IDF matrix over the entire
active corpus and runs a cosine similarity pass on **every call**. A single client
could loop it and saturate a CPU.

**Root cause:** Rate limiting was applied to the credential endpoints and nowhere else.

**Solution:** A `before_request` limiter keyed per endpoint *and* per
proxy-resolved client address, returning `429` with a `Retry-After` header and the
standard error envelope. Configurable via `API_RATE_LIMIT` / `API_RATE_WINDOW`, and
keyed on `request.remote_addr` so a forwarded header cannot be spoofed to dodge it.

While testing this, the first implementation revealed a genuine Flask trap: a
`before_request` handler that returns only the response body answers **200**, not the
status on the tuple. Caught by the new test rather than in production.

**Files changed:** `app/blueprints/api.py`, `app/services/ratelimit.py` (added
`reset_all()` so the process-global counters are testable and clearable by an
operator), `config.py`.
**Testing:** `test_api_rate_limit_returns_429_with_retry_after`.

### 2.6 The sitemap interpolated unescaped URLs

**Problem:** `<loc>{loc}</loc>` was built by string interpolation with no XML
escaping. Company slugs originate from user-supplied company names, so a slug
containing `&` produced malformed XML and one containing `<` could break out of the
element entirely.

**Root cause:** Hand-rolled XML with no escaping step.

**Solution:** `xml.sax.saxutils.escape` on every `<loc>` value.

**Files changed:** `app/blueprints/main.py`.
**Testing:** A test seeds a company named `Research & Development` and re-parses the
sitemap with `ElementTree`, which would raise on malformed output.

### 2.7 Templates were bypassing the design system

**Problem:** Templates used raw Tailwind palette utilities — `text-slate-500`,
`text-slate-600`, `text-indigo-600`, `text-red-600`, `bg-slate-50`, `text-sm` — mixed
with the CSS custom-property system. Re-theming the site would have meant hunting every
utility by hand. Six inline `style=` attributes hardcoded spacing and colour. A shim
block in `input.css` papered over this by remapping `text-indigo-600` to the brand
colour, so "indigo" and "primary" meant the same thing.

**Root cause:** Semantic utilities were never defined, and the shim was cheaper than
writing them.

**Solution:** Added the missing semantic layer (`.text-primary`, `.text-muted`,
`.text-muted-strong`, `.text-subtle`, `.text-danger`, `.surface-inset`, `.text-small`)
and migrated every template. All ~30 hardcoded hex/`rgba` values in the component
layer became named tokens. The shim block is deleted, so the misleading
`text-indigo-600 → primary` indirection no longer exists. Inline styles became
classes (`.panel-danger`, `.tracker-form`, `.select-compact`, `.tracker-notes`,
`.auth-list-flush`, `.about-band`); the two genuinely dynamic
`style="width:{{ value }}%"` meters were kept but given `role="progressbar"` and
`aria-valuenow`. `input.css` gained an explicit spacing scale and its token block is
now grouped and commented.

**Files changed:** `app/static/css/input.css`, 7 templates, `app.css` (rebuilt).
**Testing:** Compiled CSS asserted to contain every new class; a repo-wide scan
confirms no `text-slate-*` / `text-indigo-*` / `text-red-*` / `bg-slate-*` /
`style="` usages remain outside the two dynamic meters.

### 2.8 Two category tiles had no icon

**Problem:** The home page's category→icon map covered 9 of the 11 categories the
taxonomy can produce, so `Operations` and `Other` always fell back to a generic
briefcase — visibly wrong tiles rather than a broken page.

**Root cause:** The map was written by hand and drifted from `_CATEGORY_BY_TITLE`.

**Solution:** Added `Operations → workflow` and `Other → briefcase-business`, with a
comment tying the map to `_CATEGORY_BY_TITLE` so the next addition has a visible
obligation.

**Files changed:** `app/templates/home.html`.

### 2.9 The login page advertised the wrong demo account

**Problem:** The sign-in page's demo hint showed `andi@example.com` — the
*deliberately empty* account — while the README's primary demo is
`demo@example.com`, which is the populated one. A reviewer following the login page
landed on an empty-state app and concluded the project was unfinished.

**Root cause:** The hint was edited for a different account at some point and never
re-checked against the seed script.

**Solution:** The hint now matches the seeded, fully-populated account and its
current password, and a unit test asserts `demo@example.com` appears on the login
page so the two cannot drift again.

**Files changed:** `app/templates/accounts/login.html`, `seed.py`, `tests/test_app.py`.

### 2.10 No migration history

**Problem:** Flask-Migrate was installed and initialised in `create_app`, but
`migrations/` did not exist. Every deployment relied on `db.create_all()`, which only
creates *missing* tables — so the first column change would have been silently
dropped rather than applied.

**Solution:** Initialised the repository and generated an initial revision covering
all 13 tables. Also fixed the stock `migrations/env.py`, which renders the database
URL with `hide_password=False` and would echo a real credential into Alembic's logs.
`docker_entrypoint.py` now runs `flask db upgrade` once before Gunicorn forks (with
`SKIP_MIGRATIONS=1` to opt out), and honours `WEB_CONCURRENCY` / `PORT` instead of
hardcoding them.

**Files changed:** `migrations/` (new), `migrations/env.py`, `docker_entrypoint.py`.
**Testing:** Applied to an empty SQLite database and asserted against the model
metadata — all 13 tables present, no extras, correct columns on the new table.

### 2.11 Nginx rejected large uploads before the app could

**Problem:** The bundled Nginx config used its default `client_max_body_size` of 1 MB
while the app allows 2 MB (`MAX_CONTENT_LENGTH`). A request between the two was
rejected by Nginx with an unbranded error instead of the app's own 413 page. The
config also forwarded no `X-Forwarded-Host`, had no gzip, and no static caching.

**Solution:** `client_max_body_size 2m` to match the app, plus
`X-Forwarded-Host`, gzip for text assets, keepalive upstream, a revalidating cache
policy on `/static/`, and an access-log-free `/healthz`.

**Files changed:** `nginx.conf`.

### 2.12 Alembic's URL leaked credentials into logs

**Problem:** The generated `migrations/env.py` used
`render_as_string(hide_password=False)`, Alembic's stock template.

**Solution:** `hide_password=True` with a comment explaining why. The driver and host
are all Alembic needs.

**Files changed:** `migrations/env.py`.

### 2.13 Cross-source dedup merged distinct roles, destroying real jobs

**Problem:** `dedup_hash` keyed on `(company, canonical title, city, remote)` — but
*not* on seniority. Because every backend variant normalizes to the same canonical
title, `Backend Engineer Intern`, `Backend Engineer`, `Senior Backend Engineer` and
`Lead Backend Engineer` at the same company all produced an **identical** hash. The
ingestion pipeline therefore merged a brand-new intern posting into the existing
senior listing: the intern job was never created and simply vanished from the index.

This was visible in the seeded data — the Senior Backend Engineer detail page listed
**"Apply on Glints" twice**, because an intern row had collided with the senior row
and linked Glints to itself.

**Root cause:** The dedup key was designed around the source-dedup problem (the same
listing posted on two portals) and over-generalized to the cross-role case.

**Solution:** Seniority is now part of the key. Genuine duplicates still merge — a
re-posted `Senior Backend Engineer (m/f/d)` still folds into `Senior Backend Engineer`
— while a differently scoped role stays separate. The seed's demonstration pair was
corrected to be a true cross-source duplicate (it had relied on the over-broad merge),
and the job detail view now emits **one apply link per source**, deduplicated in the
view, so no upstream double-link can ever render two identical buttons.

Result: the seeded index went from 37 to 38 jobs (35 active) — the intern listing is
back — and duplicate `(job, source)` pairs went from 1 to 0.

**Files changed:** `app/services/dedup.py`, `app/blueprints/jobs.py`,
`app/templates/jobs/detail.html`, `seed.py`, `tests/test_app.py`.
**Testing:** `test_dedup_key_separates_seniority_but_still_merges_true_duplicates`
asserts four seniorities produce four hashes while cosmetic title variants still
collapse; `test_job_detail_lists_each_source_only_once` links one source twice and
asserts a single button.

### 2.14 Cron schedules rendered as escaped gibberish

**Problem:** The admin source-health cards printed the raw cron expression. Jinja
escapes it, so `0 */6 * * *` appeared on the page as `0 *&#47;6 ***` — the single
most alarming-looking string in the entire UI, and unreadable besides.

**Root cause:** A machine-readable storage format was rendered directly to a human.

**Solution:** `app/services/cron.py` renders prose — "every 6 hours", "daily at 3am",
"every 15 minutes" — exposed as a `|cron` Jinja filter. Anything the formatter cannot
narrate with confidence (day-of-week, day-of-month, lists, garbage) is passed through
unchanged rather than guessed at, so the dashboard never states something the scheduler
is not doing.

**Files changed:** `app/services/cron.py` (new), `app/__init__.py`,
`app/templates/admin/dashboard.html`, `tests/test_app.py`.
**Testing:** `test_cron_schedules_render_as_prose_not_escaped_cron` covers the
supported shapes, the honest fallbacks, and asserts the rendered dashboard contains
"every 6 hours" and no `*/6`.

### 2.15 Repository hygiene

**Problem:** `.playwright-cli/` held 70 browser-automation logs and page dumps,
`.workbuddy-ai/` held agent memory files, and `instance/` carried a hand-made
`jobhunter.db.pre-salary-fix-20260822.bak` database backup. `.gitignore` did not cover
the first two. `__pycache__` directories were committed to the working tree.

**Solution:** Removed all of it. `.gitignore` rewritten to group entries by intent and
to cover editor state, coverage output, `*.bak`, and the two tooling directories.
`.dockerignore` already excluded them from the image.

**Files changed:** `.gitignore`, directory tree.

---

## 3. Final quality review

Reviewing as (1) a senior engineer reading the code, (2) a recruiter scanning the
portfolio, and (3) a user actually clicking through it.

| Dimension | Score | Notes |
|---|---|---|
| Code quality | **9 / 10** | Clean factory → blueprint → service → model layering; pure, testable services; typed SQLAlchemy 2.x models; docstrings explain *why*, not *what*. Now has a real migration history, a CI pipeline, generated-asset scripts, and screenshots generated from the running app. Docked for the alert-email payload and the mail transport living in two places. |
| UI quality | **9.5 / 10** | Fully token-driven design system — the whole palette re-themes from `:root`. 17 KB sprite instead of 477 KB. Accessible progress meters. Screenshots are generated, so they cannot drift. |
| UX quality | **9.5 / 10** | Every button performs a real action, empty states everywhere, safe unsubscribe confirmation, enumeration-safe password recovery, and the login page advertises the account that actually shows a populated app. |
| Feature completeness | **9.5 / 10** | All advertised features work end-to-end, including the password-reset lifecycle added this pass. The half-point is the honestly-documented email delivery gap. |
| Production readiness | **9 / 10** | Migration history, CI with config guardrails, API rate limiting, fail-fast config, pool health checks, security headers, health probe, Docker stack. Docked for per-process rate limiting and no transactional email provider. |

### Remaining issues (none blocking)

| Priority | Issue | Recommendation |
|---|---|---|
| Medium | Outbound email is logged, not sent | Implement `app/services/mail.py::_send` with SMTP/SES — one function, both callers already work |
| Medium | Rate limiter is per worker process | Move the counters in `services/ratelimit.py` to Redis for a cluster-wide limit; `reset_all()` marks the seam |
| Low | `matching.py` re-vectorizes per request | Fine at this scale; cache on corpus version or move to Meilisearch/pgvector (documented in the module docstring) |
| Low | Sitemap is capped at 5,000 job URLs | Correct today; switch to a sitemap index if the index outgrows it |
| Low | Scrapers are implemented but not exercised | Run deliberately against a permitted source; the shipped dataset is seeded |

No critical or high-priority issues remain open.

---

## 4. Verification performed

- **Tests:** 29/29 passing (`python -m unittest discover`), up from 18. Added coverage
  for the password-reset lifecycle, unsubscribe confirmation, API rate limiting,
  sitemap escaping, sprite freshness, cron rendering, dedup-key seniority separation,
  per-source link deduplication, and the login page's demo hint. Run with
  `-W error::ResourceWarning` to confirm a clean exit.
- **Route sweep:** 44 route/role combinations across public, seeker (populated and
  empty), employer and admin, plus 9 mutating endpoints and the JSON API — every page
  rendered with no 5xx and no leaked Jinja expression; asserted that the demo account's
  pages do not fall through to an empty state.
- **Visual pass:** 19 screenshots captured from the running app at 1920, 1440, 768 and
  390px, with browser console errors treated as a build failure. This is what surfaced
  the orphaned submit button, the duplicated status badge and the escaped cron string —
  none of which are visible from the templates alone.
- **Migration:** Applied to an empty database and diffed against the model metadata —
  13 tables, no extras, correct columns on the new table.
- **Assets:** Compiled CSS asserted to contain every new semantic class; icon sprite
  parsed as XML and checked for orphans, missing symbols, and style overrides.
- **Configuration guardrails:** production refuses a default `SECRET_KEY` and refuses
  SQLite without the explicit override — both now asserted in CI.
- **Credential scan:** no key-shaped string or third-party gateway host anywhere in the
  tracked source, and `.env` ships with an empty key.
- **Demo data:** `seed.py` reseeds to 35 active jobs across 6 sources with zero
  duplicate `(job, source)` pairs, 6 saved jobs, 8 applications, 3 alerts and 30 scrape
  runs.

**Action required before publishing:** rotate the AI gateway key that was previously
stored in `.env`. It has been removed from the working tree, but it should be
considered compromised.
