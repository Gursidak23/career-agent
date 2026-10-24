"""ORM models for resumes, outreach, jobs, and email logs."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Raw text extracted from the uploaded PDF.
    raw_text: Mapped[str] = mapped_column(Text, default="")
    # Structured ResumeData (see schemas.ResumeData) as JSON.
    parsed: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    tailorings: Mapped[list["Tailoring"]] = relationship(
        back_populates="resume", cascade="all, delete-orphan"
    )


class Tailoring(Base):
    __tablename__ = "tailorings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(128))
    job_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Tailored ResumeData JSON.
    tailored: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ats_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ats_report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Per-bullet AI suggestions (schemas.BulletReview) the user can accept/reject.
    reviews: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # The job post this version was tailored to, if any.
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL"), nullable=True
    )

    resume: Mapped[Resume] = relationship(back_populates="tailorings")


class JobPosting(Base):
    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    source: Mapped[str] = mapped_column(String(64), default="manual")  # wellfound, yc, ...
    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    company: Mapped[str] = mapped_column(String(512), default="")
    location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    job_type: Mapped[str | None] = mapped_column(String(64), nullable=True)  # full_time...
    experience: Mapped[str | None] = mapped_column(String(64), nullable=True)  # entry...
    role_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    recruiter_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    recruiter_email: Mapped[str | None] = mapped_column(String(256), nullable=True)


class OutreachMessage(Base):
    __tablename__ = "outreach_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    recruiter_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    recruiter_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    company: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[str | None] = mapped_column(String(256), nullable=True)
    channel: Mapped[str] = mapped_column(String(32), default="email")  # email | linkedin
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL"), nullable=True
    )


class EmailCandidate(Base):
    """A discovered recruiter/company email address (from the finder chain)."""

    __tablename__ = "email_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=True
    )
    company: Mapped[str | None] = mapped_column(String(512), nullable=True)
    email: Mapped[str] = mapped_column(String(256))
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="")  # crawler|pattern|apify|agentql
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    verified: Mapped[str] = mapped_column(String(16), default="unverified")


class LinkedInLog(Base):
    """Status of an attempted LinkedIn DM send."""

    __tablename__ = "linkedin_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    profile_url: Mapped[str] = mapped_column(String(1024))
    recipient_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # sent | failed | skipped
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("outreach_messages.id", ondelete="SET NULL"), nullable=True
    )


APPLICATION_STATUSES = ["saved", "applied", "contacted", "replied", "interview", "offer", "rejected"]


class Application(Base):
    """One job you are pursuing, from saved through to offer (the tracker board)."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL"), nullable=True
    )
    company: Mapped[str] = mapped_column(String(512), default="")
    role: Mapped[str] = mapped_column(String(512), default="")
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="saved")
    tailoring_id: Mapped[int | None] = mapped_column(
        ForeignKey("tailorings.id", ondelete="SET NULL"), nullable=True
    )
    recruiter_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    to_email: Mapped[str] = mapped_column(String(256))
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # sent | failed
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_postings.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("outreach_messages.id", ondelete="SET NULL"), nullable=True
    )
