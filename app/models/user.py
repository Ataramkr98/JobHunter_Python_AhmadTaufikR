"""User-domain models: User, SavedJob, JobAlert, Application, PasswordResetToken."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import (String, Text, Boolean, DateTime, ForeignKey,
                        UniqueConstraint, Index, JSON)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db

if TYPE_CHECKING:
    from app.models.employer import Employer, Resume
    from app.models.job import Job

# A reset link is a bearer credential for the account, so it is short-lived.
RESET_TOKEN_TTL = timedelta(minutes=30)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    default_location: Mapped[str] = mapped_column(String(120), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_employer: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # soft-delete (PDP erasure)

    saved_jobs: Mapped[list["SavedJob"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    alerts: Mapped[list["JobAlert"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    employer: Mapped["Employer | None"] = relationship(
        "Employer", back_populates="user", uselist=False, cascade="all, delete-orphan")
    resumes: Mapped[list["Resume"]] = relationship(
        "Resume", back_populates="user", cascade="all, delete-orphan",
        order_by="Resume.updated_at")
    reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def issue_reset_token(self) -> tuple["PasswordResetToken", str]:
        """Create a fresh reset token, invalidating any earlier unused ones.

        Returns ``(row, plaintext)``. Only the SHA-256 digest of the token is
        persisted, so a database leak does not hand an attacker working reset
        links. The plaintext is returned rather than parked on the instance so
        it can never be flushed to the database by accident.
        """
        now = utcnow()
        for existing in self.reset_tokens:
            if existing.used_at is None:
                existing.used_at = now
        plaintext = secrets.token_urlsafe(32)
        token = PasswordResetToken(
            user_id=self.id,
            token_hash=PasswordResetToken.hash_token(plaintext),
            expires_at=now + RESET_TOKEN_TTL,
        )
        db.session.add(token)
        return token, plaintext

    @property
    def is_active(self) -> bool:
        """Prevent soft-deleted accounts from being restored by an old session."""
        return self.deleted_at is None

    @property
    def active_resume(self):
        return self.resumes[-1] if self.resumes else None

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class SavedJob(db.Model):
    __tablename__ = "saved_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_saved_user_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="saved_jobs")
    job: Mapped["Job"] = relationship("Job")


class JobAlert(db.Model):
    __tablename__ = "job_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    query: Mapped[dict] = mapped_column(JSON, default=dict)  # {q, location, type, category, salary_min}
    frequency: Mapped[str] = mapped_column(String(10), default="daily")  # instant/daily/weekly
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unsubscribe_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User | None"] = relationship(back_populates="alerts")


class PasswordResetToken(db.Model):
    """A single-use, expiring password-reset credential.

    Only the SHA-256 digest is stored, so read access to this table does not
    confer the ability to reset anyone's password.
    """
    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_password_reset_user_active", "user_id", "used_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped["User"] = relationship(back_populates="reset_tokens")

    @staticmethod
    def hash_token(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def is_usable(self) -> bool:
        expires_at = self.expires_at
        if self.used_at is not None:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > utcnow()


class Application(db.Model):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "job_id", name="uq_app_user_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    # Set when the user applies to an employer-posted job (Phase 2); null for self-tracked external jobs.
    posted_job_id: Mapped[int | None] = mapped_column(ForeignKey("posted_jobs.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="applied")  # applied/interview/offer/rejected/other
    notes: Mapped[str] = mapped_column(Text, default="")
    cover_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped["User"] = relationship(back_populates="applications")
    job: Mapped["Job"] = relationship("Job")
