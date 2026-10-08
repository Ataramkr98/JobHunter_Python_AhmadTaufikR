# Scrapers (production ingestion)

Scrapy + `scrapy-playwright` spiders that crawl job portals and feed the **same**
normalization/dedup services used by the web app — so scraped jobs and
employer-posted jobs are normalized identically.

## Setup
```bash
pip install -r ../requirements-scraping.txt
playwright install chromium
```

## Run
```bash
cd scrapers
scrapy crawl glints      # JS-rendered portal (Playwright)
scrapy crawl kalibrr     # static HTML (Scrapy)
```

In production the implemented Glints and Kalibrr spiders are scheduled by
**Celery Beat** (see `../worker/` and `../docker-compose.yml`). Each spider emits
a raw item, then `pipelines.NormalizeDedupPipeline` normalizes and deduplicates
it into the canonical `jobs` table while recording scrape-run health.

> ⚖️ **Honor `robots.txt` and each source's Terms of Service.** Prefer official
> APIs/feeds where they exist. See the PRD §5 for the full ethical-scraping
> policy and per-source compliance records.

> ⚠️ The CSS selectors in the example spiders are **illustrative** — update them
> to the live site structure before running.
