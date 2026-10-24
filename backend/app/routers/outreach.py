"""Outreach endpoints: generate messages, batch-send emails (async), status."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..models import EmailLog, JobPosting, OutreachMessage, Tailoring
from ..outreach.email_sender import send_batch, smtp_configured
from ..outreach.messages import generate_messages
from ..resume.naming import resume_filename
from ..schemas import (
    BatchSendRequest,
    BatchSendResponse,
    CandidateProfile,
    ContactHistory,
    EmailLogOut,
    MessageGenRequest,
    MessageGenResponse,
    ResumeData,
    SendItem,
    SendResult,
)
from .applications import advance, track

router = APIRouter(prefix="/api/outreach", tags=["outreach"])


def _profile(tailoring: Tailoring) -> CandidateProfile:
    """Name + a few strong, quantified bullets from a tailored resume."""
    resume = ResumeData.model_validate(tailoring.tailored or {})
    bullets = [b for e in resume.experience for b in e.bullets] + [
        b for p in resume.projects for b in p.bullets
    ]
    # Quantified bullets first; they make the most convincing outreach.
    bullets.sort(key=lambda b: not any(ch.isdigit() for ch in b))
    name = resume.contact.name
    return CandidateProfile(
        candidate_name=name.title() if name.isupper() else name,
        highlights=[b[:220] for b in bullets[:3]],
    )


@router.get("/profile/{tailoring_id}", response_model=CandidateProfile)
def profile(tailoring_id: int, db: Session = Depends(get_db)) -> CandidateProfile:
    tailoring = db.get(Tailoring, tailoring_id)
    if tailoring is None:
        raise HTTPException(status_code=404, detail="Tailoring not found")
    return _profile(tailoring)


@router.post("/generate", response_model=MessageGenResponse)
async def generate(req: MessageGenRequest, db: Session = Depends(get_db)) -> MessageGenResponse:
    # Fill in missing context so messages are grounded in the posting and resume.
    if not req.job_description and req.job_id is not None:
        job = db.get(JobPosting, req.job_id)
        if job is not None and job.description:
            req.job_description = job.description
    if req.tailoring_id is not None and not (req.candidate_name and req.candidate_highlights):
        tailoring = db.get(Tailoring, req.tailoring_id)
        if tailoring is not None:
            prof = _profile(tailoring)
            req.candidate_name = req.candidate_name or prof.candidate_name
            req.candidate_highlights = req.candidate_highlights or prof.highlights

    messages, warning = await generate_messages(req)
    for m in messages:
        db.add(
            OutreachMessage(
                recruiter_name=req.recruiter_name,
                company=req.company,
                role=req.role,
                channel=m.channel,
                subject=m.subject,
                body=m.body,
                job_id=req.job_id,
            )
        )
    db.commit()
    return MessageGenResponse(messages=messages, warning=warning)


def _attachment_for(db: Session, item: SendItem) -> Path | None:
    """Resolve the resume to attach for a send item, if requested.

    Prefers the rendered PDF; falls back to the DOCX when Tectonic is unavailable
    (so the attachment still works without a PDF toolchain).
    """
    if item.tailoring_id is None:
        return None
    tailoring = db.get(Tailoring, item.tailoring_id)
    if tailoring is None:
        return None

    # Prefer the stored PDF path when it is actually a PDF that exists.
    if tailoring.pdf_path:
        pdf = Path(tailoring.pdf_path)
        if pdf.suffix.lower() == ".pdf" and pdf.exists():
            return pdf

    # Fall back to the DOCX rendered alongside it.
    docx = get_settings().output_path / f"resume_{tailoring.id}.docx"
    if docx.exists():
        return docx
    return None


def _attachment_name(db: Session, item: SendItem, path: Path) -> str:
    """Recruiter-facing file name, e.g. Jane_Doe_Backend_Engineer_Resume.pdf."""
    tailoring = db.get(Tailoring, item.tailoring_id)
    name = ((tailoring.tailored or {}) if tailoring else {}).get("contact", {}).get("name")
    return resume_filename(name, tailoring.role if tailoring else "", path.suffix)


async def _run_send(
    items: list[SendItem],
    log_ids: list[int],
    attachments: list[str | None],
    attachment_names: list[str | None],
) -> None:
    """Background task: send emails and update their EmailLog rows."""
    att_paths = [Path(p) if p else None for p in attachments]
    results = await send_batch(items, attachments=att_paths, attachment_names=attachment_names)
    db = SessionLocal()
    try:
        for log_id, res, item in zip(log_ids, results, items, strict=False):
            row = db.get(EmailLog, log_id)
            if row is not None:
                row.status = res.status
                row.error = res.error
            if res.status == "sent" and (item.job_id or (item.company and item.role)):
                card = track(
                    db,
                    job_id=item.job_id,
                    company=item.company or "",
                    role=item.role or "",
                    tailoring_id=item.tailoring_id,
                )
                card.recruiter_email = str(item.to_email)
                advance(card, "contacted")
        db.commit()
    finally:
        db.close()


@router.post("/send", response_model=BatchSendResponse)
async def send(
    req: BatchSendRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> BatchSendResponse:
    if not req.items:
        raise HTTPException(status_code=400, detail="No recipients provided")

    # Never email the same recruiter twice by accident.
    skipped: list[SendResult] = []
    if not req.allow_repeat:
        history = {h.email.lower(): h for h in (_history(db, str(i.to_email)) for i in req.items)}
        keep = []
        for item in req.items:
            h = history[str(item.to_email).lower()]
            if h.count:
                when = h.last_sent_at.strftime("%d %b %Y") if h.last_sent_at else "earlier"
                skipped.append(
                    SendResult(to_email=str(item.to_email), status="skipped", error=f"Already emailed on {when}")
                )
            else:
                keep.append(item)
        req.items = keep

    if req.dry_run or not req.items:
        results = await send_batch(req.items, dry_run=True) if req.items else []
        return BatchSendResponse(results=skipped + results, sent=0, failed=0, queued=0)

    if not smtp_configured():
        raise HTTPException(
            status_code=400,
            detail="SMTP is not configured. Set CAREER_SMTP__HOST/USERNAME/PASSWORD.",
        )

    # Create pending log rows up front so the UI can poll /sends for progress.
    log_ids: list[int] = []
    attachments: list[str | None] = []
    attachment_names: list[str | None] = []
    for item in req.items:
        att = _attachment_for(db, item)
        attachments.append(str(att) if att else None)
        attachment_names.append(_attachment_name(db, item, att) if att else None)
        row = EmailLog(
            to_email=str(item.to_email), subject=item.subject, status="pending", job_id=item.job_id
        )
        db.add(row)
        db.flush()
        log_ids.append(row.id)
    db.commit()

    background_tasks.add_task(_run_send, req.items, log_ids, attachments, attachment_names)

    results = [SendResult(to_email=str(i.to_email), status="queued") for i in req.items]
    return BatchSendResponse(results=skipped + results, sent=0, failed=0, queued=len(results))


def _history(db: Session, email: str) -> ContactHistory:
    count, last = db.execute(
        select(func.count(EmailLog.id), func.max(EmailLog.created_at)).where(
            func.lower(EmailLog.to_email) == email.lower(), EmailLog.status == "sent"
        )
    ).one()
    return ContactHistory(email=email, count=count, last_sent_at=last)


@router.get("/contacted", response_model=ContactHistory)
def contacted(email: str, db: Session = Depends(get_db)) -> ContactHistory:
    """How often (and when last) this address was emailed successfully."""
    return _history(db, email)


@router.get("/sends", response_model=list[EmailLogOut])
def sends(limit: int = 50, db: Session = Depends(get_db)) -> list[EmailLog]:
    rows = (
        db.query(EmailLog)
        .order_by(EmailLog.created_at.desc(), EmailLog.id.desc())
        .limit(limit)
        .all()
    )
    return rows
