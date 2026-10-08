"""Job-domain models: Source, Company, Job, JobSource (provenance), ScrapeRun.

`Job` is the canonical, deduplicated entity. Each occurrence on a portal is a
`JobSource` row, so one Job can carry many source URLs (FR-B6).
"""
from datetime import datetime, timezone

from sqlalchemy import (String, Text, Integer, Boolean, DateTime, Numeric,
                        ForeignKey, UniqueConstraint, JSON)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Source(db.Model):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    base_url: Mapped[str] = mapped_column(String(255), default="")
    engine: Mapped[str] = mapped_column(String(20), default="scrapy")  # scrapy/playwright/api
    schedule_cron: Mapped[str] = mapped_column(String(40), default="0 */6 * * *")
    robots_status: Mapped[str] = mapped_column(String(20), default="allowed")
    tos_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    job_sources: Mapped[list["JobSource"]] = relationship(back_populates="source", cascade="all, delete-orphan")
    runs: Mapped[list["ScrapeRun"]] = relationship(back_populates="source", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Source {self.name}>"


class Company(db.Model):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    jobs: Mapped[list["Job"]] = relationship(back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company {self.name}>"


class Job(db.Model):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    canonical_title: Mapped[str] = mapped_column(String(255), default="", index=True)
    seniority: Mapped[str] = mapped_column(String(20), default="unknown")
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    location_raw: Mapped[str] = mapped_column(String(255), default="")
    city: Mapped[str] = mapped_column(String(120), default="", index=True)
    region: Mapped[str] = mapped_column(String(120), default="")
    country: Mapped[str] = mapped_column(String(80), default="Indonesia")
    is_remote: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    salary_min: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(3), default="IDR")
    salary_period: Mapped[str] = mapped_column(String(10), default="month")
    employment_type: Mapped[str] = mapped_column(String(20), default="full_time", index=True)
    category: Mapped[str] = mapped_column(String(80), default="Other", index=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active/expired/hidden
    dedup_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    company: Mapped["Company"] = relationship(back_populates="jobs")
    job_sources: Mapped[list["JobSource"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Job {self.title!r}>"

    @property
    def salary_display(self) -> str:
        if self.salary_min is not None and self.salary_max is not None:
            return f"{self.salary_currency} {int(self.salary_min):,}–{int(self.salary_max):,}/{self.salary_period}"
        if self.salary_min is not None:
            return f"from {self.salary_currency} {int(self.salary_min):,}/{self.salary_period}"
        if self.salary_max is not None:
            return f"up to {self.salary_currency} {int(self.salary_max):,}/{self.salary_period}"
        return "Salary not disclosed"

    @property
    def employment_type_display(self) -> str:
        return self.employment_type.replace("_", " ").title()

    @property
    def location_display(self) -> str:
        if self.is_remote and self.city:
            return f"{self.city} · Remote"
        if self.is_remote:
            return "Remote"
        return self.city or self.location_raw or "—"

    def search_text(self) -> str:
        """Text used for search indexing and AI matching."""
        skills = " ".join(str(skill) for skill in (self.skills or []))
        return f"{self.title} {self.canonical_title} {self.category} {skills} {self.description}"


class JobSource(db.Model):
    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_jobsource_source_ext"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(120), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    job: Mapped["Job"] = relationship(back_populates="job_sources")
    source: Mapped["Source"] = relationship(back_populates="job_sources")


class ScrapeRun(db.Model):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running/success/failed/partial
    items_found: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped["Source"] = relationship(back_populates="runs")
