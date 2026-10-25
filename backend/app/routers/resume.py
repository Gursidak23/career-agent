"""Resume endpoints: upload, history, score, tailor, download."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Resume, Tailoring
from ..resume.ats import score_resume
from ..resume.naming import resume_filename
from ..resume.parser import extract_text, pdf_layout, structure_resume
from ..resume.roles import ROLES, get_role
from ..resume.service import render_files
from ..resume.tailor import apply_reviews
from ..schemas import (
    AtsReport,
    BulletReview,
    ResumeData,
    ResumeSummary,
    ReviewDecision,
    ScoreRequest,
    TailoringSummary,
    TailorRequest,
    TailorResponse,
    TaskOut,
    UploadResponse,
)
from ..tasks import enqueue
from ..tasks.api import task_out

router = APIRouter(prefix="/api/resume", tags=["resume"])


def _upload_path(resume_id: int) -> Path:
    return get_settings().uploads_path / f"resume_{resume_id}.pdf"


def _save_upload(resume_id: int, content: bytes) -> None:
    """Keep the original PDF so it can be checked (ATS read-back, scan) like outputs."""
    _upload_path(resume_id).write_bytes(content)


def _is_complete(parsed: dict | None) -> bool:
    """Degraded heuristic parses have no sections; never reuse or trust those."""
    return bool(
        parsed and (parsed.get("experience") or parsed.get("projects") or parsed.get("education"))
    )


def _upload_response(resume: Resume, *, warning: str | None = None, reused: bool = False) -> UploadResponse:
    return UploadResponse(
        resume_id=resume.id,
        parsed=ResumeData.model_validate(resume.parsed or {}),
        raw_text_chars=len(resume.raw_text),
        warning=warning,
        reused=reused,
    )


def _current_report(tailoring: Tailoring, tailored: ResumeData | None = None) -> AtsReport:
    """Re-score with the current rubric (cheap) so old results reflect scorer fixes."""
    tailored = tailored or ResumeData.model_validate(tailoring.tailored or {})
    return score_resume(tailored, tailoring.role, tailoring.job_description)


def _tailor_response(
    tailoring: Tailoring,
    *,
    iterations: int | None = None,
    warning: str | None = None,
) -> TailorResponse:
    out_dir = get_settings().output_path
    stem = f"resume_{tailoring.id}"
    baseline = None
    if tailoring.resume and tailoring.resume.parsed:
        original = ResumeData.model_validate(tailoring.resume.parsed)
        baseline = score_resume(original, tailoring.role, tailoring.job_description).score
    tailored = ResumeData.model_validate(tailoring.tailored or {})
    return TailorResponse(
        tailoring_id=tailoring.id,
        resume_id=tailoring.resume_id,
        role=tailoring.role,
        tailored=tailored,
        ats=_current_report(tailoring, tailored),
        iterations=iterations,
        pdf_available=(out_dir / f"{stem}.pdf").exists(),
        docx_available=(out_dir / f"{stem}.docx").exists(),
        warning=warning,
        baseline_score=baseline,
        job_description=tailoring.job_description,
        reviews=[BulletReview.model_validate(r) for r in tailoring.reviews or []],
    )


@router.get("/roles")
def list_roles() -> list[dict[str, str]]:
    return [{"key": p.key, "label": p.label} for p in ROLES.values()]


@router.get("", response_model=list[ResumeSummary])
def list_resumes(limit: int = 50, db: Session = Depends(get_db)) -> list[ResumeSummary]:
    rows = db.scalars(select(Resume).order_by(Resume.id.desc()).limit(limit)).all()
    return [
        ResumeSummary(
            id=r.id,
            created_at=r.created_at,
            filename=r.original_filename,
            name=(r.parsed or {}).get("contact", {}).get("name", ""),
            complete=_is_complete(r.parsed),
        )
        for r in rows
    ]


@router.post("/upload", response_model=UploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    content = await file.read()
    try:
        raw_text = extract_text(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not raw_text:
        raise HTTPException(
            status_code=422, detail="No selectable text found in PDF (is it a scanned image?)."
        )

    # Same PDF uploaded before with a good parse: reuse it and skip the LLM call.
    previous = db.scalars(
        select(Resume).where(Resume.raw_text == raw_text).order_by(Resume.id.desc())
    ).first()
    if previous is not None and _is_complete(previous.parsed):
        _save_upload(previous.id, content)
        return _upload_response(previous, reused=True)

    parsed, warning = await structure_resume(raw_text, pdf_layout(content))
    resume = Resume(
        original_filename=file.filename,
        raw_text=raw_text,
        parsed=parsed.model_dump(),
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    _save_upload(resume.id, content)
    return _upload_response(resume, warning=warning)


@router.post("/score", response_model=AtsReport)
async def score(req: ScoreRequest) -> AtsReport:
    return score_resume(req.resume, req.role, req.job_description)


@router.post("/tailor", response_model=TaskOut, status_code=202)
def tailor(req: TailorRequest, db: Session = Depends(get_db)) -> TaskOut:
    """Queue a tailoring run; poll GET /api/tasks/{id} for the result.

    Runs in the worker, so it survives page reloads and API restarts, and a
    double-click while one is running returns the same task.
    """
    resume = db.get(Resume, req.resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    if not resume.parsed:
        raise HTTPException(status_code=422, detail="Resume has no parsed data")
    payload = req.model_dump()
    key = "tailor:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]
    task = enqueue(db, "tailor", payload, dedupe_key=key, active_only=True, max_attempts=2)
    db.commit()
    return task_out(task)


# Declared before "/{resume_id}" so "tailorings" is not parsed as an id.
@router.get("/tailorings", response_model=list[TailoringSummary])
def list_tailorings(
    resume_id: int | None = None, limit: int = 30, db: Session = Depends(get_db)
) -> list[TailoringSummary]:
    stmt = select(Tailoring).order_by(Tailoring.id.desc()).limit(limit)
    if resume_id is not None:
        stmt = stmt.where(Tailoring.resume_id == resume_id)
    return [
        TailoringSummary(
            id=t.id,
            resume_id=t.resume_id,
            created_at=t.created_at,
            role=t.role,
            role_label=get_role(t.role).label,
            ats_score=_current_report(t).score,
            job_snippet=(t.job_description or "").strip().split("\n")[0][:80] or None,
        )
        for t in db.scalars(stmt).all()
    ]


@router.get("/tailorings/{tailoring_id}", response_model=TailorResponse)
def get_tailoring(tailoring_id: int, db: Session = Depends(get_db)) -> TailorResponse:
    tailoring = db.get(Tailoring, tailoring_id)
    if tailoring is None:
        raise HTTPException(status_code=404, detail="Tailoring not found")
    return _tailor_response(tailoring)


@router.post("/tailorings/{tailoring_id}/review", response_model=TailorResponse)
def apply_review(
    tailoring_id: int, req: ReviewDecision, db: Session = Depends(get_db)
) -> TailorResponse:
    """Accept/reject each suggested rewrite, then re-score and re-render."""
    tailoring = db.get(Tailoring, tailoring_id)
    if tailoring is None:
        raise HTTPException(status_code=404, detail="Tailoring not found")
    reviews = [BulletReview.model_validate(r) for r in tailoring.reviews or []]
    if len(req.applied) != len(reviews):
        raise HTTPException(status_code=422, detail=f"Expected {len(reviews)} decisions")
    reviews = [r.model_copy(update={"applied": a}) for r, a in zip(reviews, req.applied, strict=True)]
    resume = apply_reviews(ResumeData.model_validate(tailoring.tailored or {}), reviews)
    report = score_resume(resume, tailoring.role, tailoring.job_description)
    tailoring.tailored = resume.model_dump()
    tailoring.reviews = [r.model_dump() for r in reviews]
    tailoring.ats_score = report.score
    tailoring.ats_report = report.model_dump()
    render_files(tailoring, resume)
    db.commit()
    return _tailor_response(tailoring)


@router.post("/tailorings/{tailoring_id}/render", response_model=TailorResponse)
def rerender(tailoring_id: int, db: Session = Depends(get_db)) -> TailorResponse:
    """Re-render PDF/DOCX with the current template (e.g. after an ATS-safety fix)."""
    tailoring = db.get(Tailoring, tailoring_id)
    if tailoring is None:
        raise HTTPException(status_code=404, detail="Tailoring not found")
    render_files(tailoring, ResumeData.model_validate(tailoring.tailored or {}))
    db.commit()
    return _tailor_response(tailoring)


@router.get("/{resume_id}", response_model=UploadResponse)
def get_resume(resume_id: int, db: Session = Depends(get_db)) -> UploadResponse:
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return _upload_response(resume)


@router.get("/{tailoring_id}/download")
def download(tailoring_id: int, fmt: str = "pdf", db: Session = Depends(get_db)) -> FileResponse:
    tailoring = db.get(Tailoring, tailoring_id)
    if tailoring is None:
        raise HTTPException(status_code=404, detail="Tailoring not found")

    out_dir = get_settings().output_path
    media_by_fmt = {
        "tex": "application/x-tex",
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    if fmt not in media_by_fmt:
        raise HTTPException(status_code=400, detail="fmt must be one of: pdf, docx, tex")
    path = out_dir / f"resume_{tailoring_id}.{fmt}"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{fmt.upper()} not available. PDF requires Tectonic; try fmt=docx or fmt=tex.",
        )
    name = (tailoring.tailored or {}).get("contact", {}).get("name")
    return FileResponse(
        path, media_type=media_by_fmt[fmt], filename=resume_filename(name, tailoring.role, fmt)
    )
