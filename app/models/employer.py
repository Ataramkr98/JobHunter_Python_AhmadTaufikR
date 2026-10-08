"""Phase-2 models: Employer, PostedJob (employer portal), Resume (resume builder)."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import String, Text, DateTime, ForeignKey, Numeric, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.user import User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Employer(db.Model):
    __tablename__ = "employers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(200), default="")
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    website: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="employer")
    posted_jobs: Mapped[list["PostedJob"]] = relationship(back_populates="employer", cascade="all, delete-orphan")


class PostedJob(db.Model):
    """A job posted by an employer. On creation we also build a canonical `Job`
    (source = 'Employer Portal') so it appears in search and AI matching uniformly."""
    __tablename__ = "posted_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    employer_id: Mapped[int] = mapped_column(ForeignKey("employers.id"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(160), default="")
    employment_type: Mapped[str] = mapped_column(String(20), default="full_time")
    salary_min: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(3), default="IDR")
    category: Mapped[str] = mapped_column(String(80), default="Other")
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/closed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    employer: Mapped["Employer"] = relationship(back_populates="posted_jobs")
    job: Mapped["Job | None"] = relationship("Job")


class Resume(db.Model):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    headline: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    location: Mapped[str] = mapped_column(String(160), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    experiences: Mapped[list] = mapped_column(JSON, default=list)   # [{role, company, start, end, description}]
    educations: Mapped[list] = mapped_column(JSON, default=list)    # [{degree, school, year}]
    skills: Mapped[list] = mapped_column(JSON, default=list)        # ["Python", ...]
    links: Mapped[dict] = mapped_column(JSON, default=dict)         # {linkedin, github, portfolio}
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="resumes")
