"""Application tracker: one card per job you pursue, saved -> offer."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Application, EmailLog, JobPosting, Tailoring
from ..schemas import ApplicationCreate, ApplicationOut, ApplicationUpdate

router = APIRouter(prefix="/api/applications", tags=["applications"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _out(db: Session, app: Application) -> ApplicationOut:
    out = ApplicationOut.model_validate(app, from_attributes=True)
    job = db.get(JobPosting, app.job_id) if app.job_id else None
    if job is not None:
        out.location = job.location
        out.url = out.url or job.url
    if app.tailoring_id:
        tailoring = db.get(Tailoring, app.tailoring_id)
        out.tailoring_score = tailoring.ats_score if tailoring else None
    # Emails count when linked to the job, or sent to this card's recruiter.
    conds = []
    if app.job_id:
        conds.append(EmailLog.job_id == app.job_id)
    if app.recruiter_email:
        conds.append(func.lower(EmailLog.to_email) == app.recruiter_email.lower())
    if conds:
        count, last = db.execute(
            select(func.count(EmailLog.id), func.max(EmailLog.created_at)).where(
                or_(*conds), EmailLog.status == "sent"
            )
        ).one()
        out.emails_sent, out.last_emailed_at = count, last
    return out


def track(
    db: Session,
    *,
    job_id: int | None,
    company: str = "",
    role: str = "",
    url: str | None = None,
    status: str = "saved",
    tailoring_id: int | None = None,
) -> Application:
    """Get-or-create the card for a job (one card per job, or per company+role)."""
    if job_id:
        query = select(Application).where(Application.job_id == job_id)
    else:
        query = select(Application).where(
            func.lower(Application.company) == company.lower(), func.lower(Application.role) == role.lower()
        )
    app = db.scalars(query).first()
    if app is None:
        job = db.get(JobPosting, job_id) if job_id else None
        app = Application(
            job_id=job_id,
            company=company or (job.company if job else ""),
            role=role or (job.title if job else ""),
            url=url or (job.url if job else None),
            status=status,
            recruiter_email=job.recruiter_email if job else None,
        )
        db.add(app)
    if tailoring_id and not app.tailoring_id:
        app.tailoring_id = tailoring_id
    return app


_ORDER = ["saved", "applied", "contacted", "replied", "interview", "offer", "rejected"]


def advance(app: Application, status: str) -> None:
    """Move forward only (an automatic 'contacted' never undoes 'interview')."""
    if app.status == "rejected" or _ORDER.index(status) <= _ORDER.index(app.status):
        return
    set_status(app, status)


def set_status(app: Application, status: str) -> None:
    app.status = status
    if status == "applied" and app.applied_at is None:
        app.applied_at = _now()
    if status == "contacted" and app.contacted_at is None:
        app.contacted_at = _now()


@router.get("", response_model=list[ApplicationOut])
def list_applications(db: Session = Depends(get_db)) -> list[ApplicationOut]:
    rows = db.scalars(select(Application).order_by(Application.updated_at.desc(), Application.id.desc()))
    return [_out(db, a) for a in rows]


@router.post("", response_model=ApplicationOut)
def create_application(req: ApplicationCreate, db: Session = Depends(get_db)) -> ApplicationOut:
    if not req.job_id and not (req.company.strip() and req.role.strip()):
        raise HTTPException(status_code=422, detail="Give a job, or a company and role.")
    if req.job_id and db.get(JobPosting, req.job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    app = track(
        db,
        job_id=req.job_id,
        company=req.company.strip(),
        role=req.role.strip(),
        url=req.url,
        status=req.status,
        tailoring_id=req.tailoring_id,
    )
    if req.notes:
        app.notes = req.notes
    db.commit()
    db.refresh(app)
    return _out(db, app)


@router.patch("/{app_id}", response_model=ApplicationOut)
def update_application(app_id: int, req: ApplicationUpdate, db: Session = Depends(get_db)) -> ApplicationOut:
    app = db.get(Application, app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if req.status is not None:
        set_status(app, req.status)
    for field in ("notes", "tailoring_id", "recruiter_email"):
        value = getattr(req, field)
        if value is not None:
            setattr(app, field, value or None)
    db.commit()
    db.refresh(app)
    return _out(db, app)


@router.delete("/{app_id}")
def delete_application(app_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    app = db.get(Application, app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Application not found")
    db.delete(app)
    db.commit()
    return {"ok": True}
