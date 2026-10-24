"""Jobs endpoints: list/filter postings and refresh from a source."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..logging_setup import get_logger
from ..models import JobPosting
from ..outreach.email_finder import get_service
from ..outreach.filters import EXPERIENCE_LEVELS, JOB_TYPES, build_job_query
from ..outreach.scraper import get_source, source_names
from ..schemas import JobOut, JobRefreshRequest

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
log = get_logger(__name__)


async def _enrich_jobs(job_ids: list[int]) -> None:
    """Background: run the email finder for jobs missing a recruiter email."""
    service = get_service()
    db = SessionLocal()
    try:
        for job_id in job_ids:
            job = db.get(JobPosting, job_id)
            if job is None or job.recruiter_email:
                continue
            try:
                candidates = await service.find(
                    name=job.recruiter_name, company=job.company, job_url=job.url
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("enrich failed for job %s: %s", job_id, exc)
                continue
            if candidates:
                job.recruiter_email = candidates[0].email
                db.commit()
    finally:
        db.close()


@router.get("/meta")
def meta() -> dict[str, list[str]]:
    return {
        "sources": source_names(),
        "job_types": JOB_TYPES,
        "experience_levels": EXPERIENCE_LEVELS,
    }


@router.get("", response_model=list[JobOut])
def list_jobs(
    role_category: str | None = None,
    job_type: str | None = None,
    experience: str | None = None,
    location: str | None = None,
    company: str | None = None,
    has_email: bool | None = None,
    search: str | None = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
) -> list[JobPosting]:
    stmt = build_job_query(
        role_category=role_category,
        job_type=job_type,
        experience=experience,
        location=location,
        company=company,
        has_email=has_email,
        search=search,
    ).limit(limit)
    return list(db.scalars(stmt).all())


@router.post("/refresh", response_model=list[JobOut])
def refresh(
    req: JobRefreshRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> list[JobPosting]:
    try:
        source = get_source(req.source)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        records = source.fetch(query=req.query, location=req.location, limit=req.limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    created: list[JobPosting] = []
    for rec in records:
        # De-dupe on (source, external_id) when available.
        existing = None
        if rec.external_id:
            existing = (
                db.query(JobPosting)
                .filter_by(source=rec.source, external_id=rec.external_id)
                .first()
            )
        if existing:
            # Refresh fields so parser fixes and edited postings reach old rows,
            # but never drop an email found earlier by enrichment.
            for field in (
                "title", "company", "location", "job_type", "experience",
                "role_category", "description", "url", "recruiter_name",
            ):
                setattr(existing, field, getattr(rec, field))
            existing.recruiter_email = rec.recruiter_email or existing.recruiter_email
            created.append(existing)
            continue
        job = JobPosting(
            source=rec.source,
            external_id=rec.external_id,
            title=rec.title,
            company=rec.company,
            location=rec.location,
            job_type=rec.job_type,
            experience=rec.experience,
            role_category=rec.role_category,
            description=rec.description,
            url=rec.url,
            recruiter_name=rec.recruiter_name,
            recruiter_email=rec.recruiter_email,
        )
        db.add(job)
        created.append(job)
    db.commit()
    for job in created:
        db.refresh(job)

    if req.enrich_emails:
        missing = [job.id for job in created if not job.recruiter_email]
        if missing:
            background.add_task(_enrich_jobs, missing)

    return created
