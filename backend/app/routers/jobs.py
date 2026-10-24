"""Jobs endpoints: list/filter postings and refresh from a source."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..logging_setup import get_logger
from ..models import Application, JobPosting, Resume
from ..outreach.email_finder import get_service
from ..outreach.filters import EXPERIENCE_LEVELS, JOB_TYPES, build_job_query
from ..outreach.job_feed import ingest
from ..outreach.matching import match_job, resume_lower
from ..outreach.scraper import source_names
from ..schemas import JobOut, JobRefreshRequest, ResumeData

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
    resume_id: int | None = None,
    sort: str = Query("newest", pattern="^(newest|match)$"),
    min_match: int = Query(0, ge=0, le=100),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    stmt = build_job_query(
        role_category=role_category,
        job_type=job_type,
        experience=experience,
        location=location,
        company=company,
        has_email=has_email,
        search=search,
    )
    ranked = resume_id is not None and (sort == "match" or min_match > 0)
    # Ranking needs every candidate scored before the limit applies.
    rows = list(db.scalars(stmt.limit(2000 if ranked else limit)).all())

    resume = db.get(Resume, resume_id) if resume_id is not None else None
    text = resume_lower(ResumeData.model_validate(resume.parsed)) if resume and resume.parsed else None
    tracked = {
        a.job_id: a
        for a in db.scalars(select(Application).where(Application.job_id.in_([r.id for r in rows])))
    }

    out: list[JobOut] = []
    for row in rows:
        job = JobOut.model_validate(row, from_attributes=True)
        if text is not None:
            m = match_job(text, row.title, row.description, row.role_category)
            job.match_score, job.match_matched, job.match_missing = m.score, m.matched, m.missing
        if row.id in tracked:
            job.application_id, job.application_status = tracked[row.id].id, tracked[row.id].status
        out.append(job)

    if text is not None and min_match:
        out = [j for j in out if (j.match_score or 0) >= min_match]
    if text is not None and sort == "match":
        out.sort(key=lambda j: j.match_score or 0, reverse=True)
    return out[:limit]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobPosting:
    job = db.get(JobPosting, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/refresh", response_model=list[JobOut])
def refresh(
    req: JobRefreshRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> list[JobOut]:
    try:
        touched, new_ids = ingest(db, req.source, query=req.query, location=req.location, limit=req.limit)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.enrich_emails:
        missing = [job.id for job in touched if not job.recruiter_email]
        if missing:
            background.add_task(_enrich_jobs, missing)

    out = []
    for job in touched:
        item = JobOut.model_validate(job, from_attributes=True)
        item.is_new = job.id in new_ids
        out.append(item)
    return out
