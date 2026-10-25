"""Tailoring as a reusable service: run by the task worker, not the HTTP request."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import JobPosting, Resume, Tailoring
from ..schemas import ResumeData
from ..system import events
from .docx_render import render_docx
from .latex import render_pdf
from .tailor import tailor_resume


def render_files(tailoring: Tailoring, resume: ResumeData) -> None:
    """(Re)write the PDF (or .tex without Tectonic) and the .docx for a tailoring."""
    out_dir = get_settings().output_path
    stem = f"resume_{tailoring.id}"
    render = render_pdf(resume, out_dir, stem=stem)
    try:
        render_docx(resume, out_dir, stem=stem)
    except Exception:  # noqa: BLE001, S110 - docx is a best-effort extra format
        pass
    tailoring.pdf_path = str(render.pdf_path) if render.pdf_path else str(render.tex_path)


async def run_tailoring(
    db: Session,
    *,
    resume_id: int,
    role: str,
    job_description: str | None,
    job_id: int | None = None,
    target_score: float = 90.0,
    max_iterations: int = 4,
    progress: Callable[[str], None] | None = None,
) -> dict:
    from ..routers.applications import track

    resume = db.get(Resume, resume_id)
    if resume is None or not resume.parsed:
        raise ValueError("Resume not found or not parsed")
    if progress:
        progress("Rewriting and scoring drafts")
    result = await tailor_resume(
        ResumeData.model_validate(resume.parsed),
        role,
        job_description,
        target_score=target_score,
        max_iterations=max_iterations,
    )
    tailoring = Tailoring(
        resume_id=resume.id,
        role=role,
        job_description=job_description,
        job_id=job_id,
        tailored=result.resume.model_dump(),
        ats_score=result.report.score,
        ats_report=result.report.model_dump(),
        reviews=[r.model_dump() for r in result.reviews],
    )
    db.add(tailoring)
    db.commit()
    db.refresh(tailoring)
    if progress:
        progress("Rendering PDF and Word files")
    render_files(tailoring, result.resume)
    if job_id and db.get(JobPosting, job_id) is not None:
        # Tailoring to a post means you're pursuing it: put it on the board with
        # this (newest) resume version.
        track(db, job_id=job_id).tailoring_id = tailoring.id
    db.commit()
    events.record(
        "tailoring.created",
        f"Optimized resume for {role}: ATS {result.report.score:.0f}"
        + (f" ({len([r for r in result.reviews if r.flags])} rewrites held back)" if result.reviews else ""),
        tailoring_id=tailoring.id,
        job_id=job_id,
    )
    return {"tailoring_id": tailoring.id, "iterations": result.iterations, "warning": result.warning}
