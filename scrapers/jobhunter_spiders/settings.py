import sys
from pathlib import Path

# Scrapy is launched from scrapers/, while the shared Flask app lives one level
# above it. Make that project root importable for the shared ingestion pipeline.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

BOT_NAME = "jobhunter_spiders"
SPIDER_MODULES = ["jobhunter_spiders.spiders"]
NEWSPIDER_MODULE = "jobhunter_spiders.spiders"

# --- Polite crawling (PRD §5.4) ---
ROBOTSTXT_OBEY = True
DOWNLOAD_DELAY = 2
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2
AUTOTHROTTLE_MAX_DELAY = 10
CONCURRENT_REQUESTS_PER_DOMAIN = 2
RANDOMIZE_DOWNLOAD_DELAY = True

# Identify ourselves (PRD ethical-scraping policy).
USER_AGENT = "JobHunterBot/1.0 (+https://jobhunter.example; ops@jobhunter.example)"

# Normalize + dedup into the canonical jobs table.
ITEM_PIPELINES = {"jobhunter_spiders.pipelines.NormalizeDedupPipeline": 300}

# --- Playwright (for JS-rendered sources) ---
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
FEED_EXPORT_ENCODING = "utf-8"
