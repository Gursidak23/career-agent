"""Email finder endpoints: discover and verify recruiter/company emails."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import EmailCandidate as EmailCandidateModel
from ..models import JobPosting
from ..outreach.email_finder import get_service
from ..outreach.email_finder.domain import resolve_domain
from ..outreach.email_finder.verify import verify_email
from ..schemas import (
    EmailCandidateOut,
    EmailFindRequest,
    EmailFindResponse,
    EmailVerifyRequest,
    EmailVerifyResponse,
)

router = APIRouter(prefix="/api/email", tags=["email"])


def _to_out(cand) -> EmailCandidateOut:
    return EmailCandidateOut(
        email=cand.email,
        source=cand.source,
        confidence=round(cand.confidence, 3),
        verified=cand.verified,
        name=cand.name,
    )


@router.post("/find", response_model=EmailFindResponse)
async def find(req: EmailFindRequest, db: Session = Depends(get_db)) -> EmailFindResponse:
    company = req.company
    name = req.name
    domain = req.domain
    job_url = req.job_url

    # Pull missing context from the linked job posting, if provided.
    if req.job_id is not None:
        job = db.get(JobPosting, req.job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        company = company or job.company
        name = name or job.recruiter_name
        job_url = job_url or job.url

    if not company:
        raise HTTPException(status_code=400, detail="company is required")

    candidates = await get_service().find(
        name=name, company=company, domain=domain, job_url=job_url
    )

    # Persist discoveries for later reference.
    for cand in candidates:
        db.add(
            EmailCandidateModel(
                job_id=req.job_id,
                company=company,
                email=cand.email,
                name=cand.name,
                source=cand.source,
                confidence=cand.confidence,
                verified=cand.verified,
            )
        )
    # If linked to a job and we found a strong candidate, fill recruiter_email.
    if req.job_id is not None and candidates:
        best = candidates[0]
        job = db.get(JobPosting, req.job_id)
        if job is not None and not job.recruiter_email:
            job.recruiter_email = best.email
    db.commit()

    out = [_to_out(c) for c in candidates]
    resolved = resolve_domain(company, domain, job_url)
    return EmailFindResponse(candidates=out, best=out[0] if out else None, domain=resolved)


@router.post("/verify", response_model=EmailVerifyResponse)
async def verify(req: EmailVerifyRequest) -> EmailVerifyResponse:
    grade = await verify_email(str(req.email))
    return EmailVerifyResponse(email=str(req.email), verified=grade)
