"""Pull postings from a source into the database, and the scheduled digest.

Shared by the /api/jobs/refresh route and the optional background scheduler
(CAREER_SCRAPER__AUTO_REFRESH_HOURS), which also emails a digest of new,
well-matched jobs when CAREER_SCRAPER__DIGEST_EMAIL and SMTP are configured.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..logging_setup import get_logger
from ..models import JobPosting, Resume
from ..schemas import ResumeData, SendItem
from .email_sender import send_batch, smtp_configured
from .matching import match_job, resume_lower
from .scraper import get_source

log = get_logger(__name__)

_FIELDS = (
    "title", "company", "location", "job_type", "experience",
    "role_category", "description", "url", "recruiter_name",
)


def ingest(
    db: Session, source_name: str, *, query: str | None = None, location: str | None = None, limit: int = 25
) -> tuple[list[JobPosting], set[int]]:
    """Fetch from a source and upsert. Returns (all postings touched, ids of new ones).

    Raises KeyError for an unknown source and RuntimeError when the source fails.
    """
    records = get_source(source_name).fetch(query=query, location=location, limit=limit)
    touched: list[JobPosting] = []
    new: list[JobPosting] = []
    for rec in records:
        # De-dupe on (source, external_id) when available.
        existing = None
        if rec.external_id:
            existing = db.query(JobPosting).filter_by(source=rec.source, external_id=rec.external_id).first()
        if existing:
            # Refresh fields so parser fixes and edited postings reach old rows,
            # but never drop an email found earlier by enrichment.
            for field in _FIELDS:
                setattr(existing, field, getattr(rec, field))
            existing.recruiter_email = rec.recruiter_email or existing.recruiter_email
            touched.append(existing)
            continue
        job = JobPosting(
            source=rec.source,
            external_id=rec.external_id,
            recruiter_email=rec.recruiter_email,
            **{f: getattr(rec, f) for f in _FIELDS},
        )
        db.add(job)
        touched.append(job)
        new.append(job)
    db.commit()
    for job in touched:
        db.refresh(job)
    return touched, {j.id for j in new}


def latest_resume(db: Session) -> ResumeData | None:
    """Most recent resume with a real (non-degraded) parse."""
    for row in db.scalars(select(Resume).order_by(Resume.id.desc()).limit(20)):
        parsed = row.parsed or {}
        if parsed.get("experience") or parsed.get("projects") or parsed.get("education"):
            return ResumeData.model_validate(parsed)
    return None


def digest_body(jobs: list[tuple[int, JobPosting]]) -> str:
    lines = [f"{len(jobs)} new job(s) matching your resume:\n"]
    for score, job in jobs:
        lines.append(f"- {score}%  {job.title} at {job.company} ({job.location or 'location n/a'})")
        if job.url:
            lines.append(f"  {job.url}")
    lines.append("\nOpen Career Agent to tailor your resume and draft outreach.")
    return "\n".join(lines)


async def run_scheduled_refresh() -> int:
    """One scheduled fetch (+ digest). Returns the number of new postings."""
    cfg = get_settings().scraper
    db = SessionLocal()
    try:
        _, new_ids = await asyncio.to_thread(ingest, db, cfg.auto_refresh_source, limit=50)
        log.info("scheduled job refresh: %d new posting(s)", len(new_ids))
        if not (new_ids and cfg.digest_email and smtp_configured()):
            return len(new_ids)
        resume = latest_resume(db)
        if resume is None:
            return len(new_ids)
        text = resume_lower(resume)
        jobs = db.scalars(select(JobPosting).where(JobPosting.id.in_(new_ids))).all()
        scored = sorted(
            ((match_job(text, j.title, j.description, j.role_category).score, j) for j in jobs),
            key=lambda x: x[0],
            reverse=True,
        )
        good = [(s, j) for s, j in scored if s >= cfg.digest_min_match][:15]
        if good:
            stamp = datetime.now(timezone.utc).strftime("%d %b")
            await send_batch(
                [SendItem(to_email=cfg.digest_email, subject=f"Career Agent: {len(good)} new matching jobs ({stamp})", body=digest_body(good))]
            )
        return len(new_ids)
    finally:
        db.close()


async def scheduler_loop() -> None:
    """Background task started at app startup when auto_refresh_hours > 0."""
    hours = get_settings().scraper.auto_refresh_hours
    while True:
        try:
            await run_scheduled_refresh()
        except Exception as exc:  # noqa: BLE001 - keep the loop alive on any failure
            log.warning("scheduled job refresh failed: %s", exc)
        await asyncio.sleep(max(0.25, hours) * 3600)
