"""Task -> API representation."""

from __future__ import annotations

from ..models import Task
from ..schemas import TaskOut


def _summary(task: Task) -> str:
    p = task.payload or {}
    if task.kind == "send_email":
        item = p.get("item") or {}
        return f"Email to {item.get('to_email')}: {item.get('subject', '')}"[:160]
    if task.kind == "tailor":
        return f"Optimize resume for {p.get('role')}" + (" + job post" if p.get("job_description") else "")
    if task.kind == "linkedin_batch":
        return f"{len(p.get('items') or [])} LinkedIn DM(s)"
    if task.kind == "enrich_emails":
        return f"Find recruiter emails for {len(p.get('job_ids') or [])} job(s)"
    if task.kind == "refresh_jobs":
        return f"Fetch jobs from {p.get('source', 'all')}"
    if task.kind == "backup":
        return "Back up database and uploads"
    return task.kind


def task_out(task: Task) -> TaskOut:
    out = TaskOut.model_validate(task, from_attributes=True)
    out.summary = _summary(task)
    return out
