"""Resume quality checks and interview prep.

- ATS read-back: what three PDF text extractors recover from the PDF
- Recruiter 6-second scan: attention heatmap + what's seen at a glance
- Requirement evidence: job requirements mapped to resume lines (LLM)
- Defend-your-resume drill: probing questions and graded answers (LLM)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import JobPosting, Resume, Tailoring
from ..resume import drill
from ..resume.ats_check import check_pdf
from ..resume.evidence import analyze
from ..resume.scan import scan_pdf
from ..schemas import (
    AtsCheckReport,
    DrillAnswer,
    DrillGrade,
    DrillQuestion,
    DrillStart,
    EvidenceReport,
    EvidenceRequest,
    ResumeData,
    ScanReport,
)

router = APIRouter(tags=["checks"])


def _resume_data(db: Session, resume_id: int | None, tailoring_id: int | None) -> tuple[ResumeData, Tailoring | None]:
    if tailoring_id is not None:
        tailoring = db.get(Tailoring, tailoring_id)
        if tailoring is None:
            raise HTTPException(status_code=404, detail="Tailoring not found")
        return ResumeData.model_validate(tailoring.tailored or {}), tailoring
    resume = db.get(Resume, resume_id) if resume_id is not None else None
    if resume is None or not resume.parsed:
        raise HTTPException(status_code=404, detail="Resume not found")
    return ResumeData.model_validate(resume.parsed), None


def _target(
    db: Session, resume_id: int | None, tailoring_id: int | None, role: str | None
) -> tuple[Path, ResumeData, str, str | None]:
    """(pdf path, resume data, role, job description) for a tailoring or an original upload."""
    if tailoring_id is None and resume_id is None:
        raise HTTPException(status_code=422, detail="Give tailoring_id or resume_id")
    data, tailoring = _resume_data(db, resume_id, tailoring_id)
    if tailoring is not None:
        path = get_settings().output_path / f"resume_{tailoring.id}.pdf"
        if not path.exists():
            raise HTTPException(status_code=404, detail="No PDF for this version (Tectonic needed)")
        return path, data, tailoring.role, tailoring.job_description
    path = get_settings().uploads_path / f"resume_{resume_id}.pdf"
    if not path.exists():
        raise HTTPException(
            status_code=404, detail="The original PDF wasn't kept for this upload. Upload it again to check it."
        )
    return path, data, role or "software_developer", None


@router.get("/api/checks/ats", response_model=AtsCheckReport)
def ats_readback(
    tailoring_id: int | None = None, resume_id: int | None = None, db: Session = Depends(get_db)
) -> AtsCheckReport:
    path, data, _, _ = _target(db, resume_id, tailoring_id, None)
    return check_pdf(path, data)


@router.get("/api/checks/scan", response_model=ScanReport)
def recruiter_scan(
    tailoring_id: int | None = None,
    resume_id: int | None = None,
    role: str | None = Query(None, description="Target role for an original upload"),
    db: Session = Depends(get_db),
) -> ScanReport:
    path, data, target_role, jd = _target(db, resume_id, tailoring_id, role)
    return scan_pdf(path, data, target_role, jd)[0]


@router.get("/api/checks/scan.png")
def recruiter_scan_image(
    tailoring_id: int | None = None,
    resume_id: int | None = None,
    role: str | None = None,
    db: Session = Depends(get_db),
) -> Response:
    path, data, target_role, jd = _target(db, resume_id, tailoring_id, role)
    return Response(scan_pdf(path, data, target_role, jd)[1], media_type="image/png")


@router.post("/api/checks/evidence", response_model=EvidenceReport)
async def requirement_evidence(req: EvidenceRequest, db: Session = Depends(get_db)) -> EvidenceReport:
    data, tailoring = _resume_data(db, req.resume_id, req.tailoring_id)
    jd = req.job_description
    if not jd and req.job_id is not None:
        job = db.get(JobPosting, req.job_id)
        jd = f"{job.title} at {job.company}\n\n{job.description or ''}" if job else None
    if not jd and tailoring is not None:
        jd = tailoring.job_description
    if not jd or len(jd.split()) < 15:
        raise HTTPException(status_code=422, detail="Paste the job description (or pick a job) first.")
    try:
        return await analyze(data, jd)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/drill/questions", response_model=list[DrillQuestion])
async def drill_questions(req: DrillStart, db: Session = Depends(get_db)) -> list[DrillQuestion]:
    data, _ = _resume_data(db, req.resume_id, req.tailoring_id)
    try:
        return await drill.questions(data, req.count)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/drill/grade", response_model=DrillGrade)
async def drill_grade(req: DrillAnswer) -> DrillGrade:
    try:
        return await drill.grade(req.claim, req.question, req.look_for, req.answer)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
