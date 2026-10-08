"""Normalize + dedup scraped items into the canonical jobs table.

Reuses the SAME services as the web app so scraped and employer-posted jobs are
normalized identically. Runs inside a Flask app context.
"""
import hashlib
import re
from datetime import datetime, timezone

from sqlalchemy import func

from app import create_app
from app.extensions import db
from app.models.job import Job, Company, Source, JobSource, ScrapeRun
from app.services.normalization import normalize_job
from app.services.dedup import find_matching_job


def _utcnow():
    return datetime.now(timezone.utc)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "company"


class NormalizeDedupPipeline:
    def open_spider(self, spider):
        self.app = create_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        source_name = getattr(spider, "source_name", spider.name)
        self.source = Source.query.filter_by(name=source_name).first()
        if not self.source:
            start_urls = getattr(spider, "start_urls", [])
            self.source = Source(
                name=source_name,
                base_url=start_urls[0] if start_urls else "",
                engine="playwright" if getattr(spider, "uses_playwright", False) else "scrapy",
                enabled=True,
            )
            db.session.add(self.source)
            db.session.flush()
        self.run = ScrapeRun(source_id=self.source.id, status="running")
        db.session.add(self.run)
        db.session.commit()

    def close_spider(self, spider):
        try:
            self.run.finished_at = _utcnow()
            if self.run.status == "running":
                reason = None
                if getattr(spider, "crawler", None) is not None:
                    reason = spider.crawler.stats.get_value("finish_reason")
                if reason not in (None, "finished"):
                    self.run.status = "failed"
                    self.run.error_detail = self.run.error_detail or f"Spider closed: {reason}"
                elif getattr(self.run, "errors", 0):
                    self.run.status = "partial" if self.run.items_found else "failed"
                else:
                    self.run.status = "success"
            db.session.commit()
        finally:
            self.ctx.pop()

    def process_item(self, item, spider):
        raw = dict(item)
        self.run.items_found += 1
        company_name = (raw.get("company") or "").strip()
        if not company_name or not raw.get("title"):
            self.run.errors += 1
            self.run.error_detail = "Skipped an item missing company or title."
            db.session.commit()
            return item  # skip incomplete rows

        company = Company.query.filter(func.lower(Company.name) == company_name.lower()).first()
        if not company:
            base_slug = _slugify(company_name)
            slug = base_slug
            suffix = 2
            while Company.query.filter_by(slug=slug).first():
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            company = Company(name=company_name, slug=slug)
            db.session.add(company)
            db.session.flush()

        norm = normalize_job(raw)
        existing, h = find_matching_job(company.name, raw["title"], raw.get("location", ""))
        if existing:
            existing.last_seen_at = _utcnow()
            job = existing
            self.run.items_updated += 1
        else:
            job = Job(company_id=company.id, posted_at=_utcnow(), status="active", **norm)
            job.dedup_hash = h
            db.session.add(job)
            db.session.flush()
            self.run.items_new += 1

        # Provenance: one JobSource per (source, external_id)
        ext = (raw.get("external_id") or raw.get("url") or "").strip()
        if not ext:
            stable = f"{company_name}|{raw.get('title', '')}|{raw.get('location', '')}"
            ext = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:32]
        elif len(ext) > 120:
            ext = hashlib.sha256(ext.encode("utf-8")).hexdigest()[:32]
        provenance = JobSource.query.filter_by(source_id=self.source.id, external_id=ext).first()
        if provenance:
            provenance.job_id = job.id
            provenance.url = raw.get("url", "")
            provenance.scraped_at = _utcnow()
        else:
            db.session.add(JobSource(job_id=job.id, source_id=self.source.id,
                                     external_id=ext, url=raw.get("url", "")))
        db.session.commit()
        return item
