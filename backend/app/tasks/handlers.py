"""What each task kind does. Handlers run in the worker process.

A handler takes the task payload and a context, returns a JSON-able result, and
raises to fail (the queue retries with backoff). Raise Reschedule to postpone
without using up an attempt (e.g. quiet hours).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..db import SessionLocal
from ..models import EmailLog, LinkedInLog
from ..schemas import LinkedInSendItem, SendItem
from ..system import events, state


class Reschedule(Exception):  # noqa: N818 - control flow, not an error
    """Run this task again at `when` (UTC naive) without counting an attempt."""

    def __init__(self, when: datetime, reason: str) -> None:
        super().__init__(reason)
        self.when = when


@dataclass
class TaskContext:
    task_id: int
    attempt: int
    max_attempts: int
    set_progress: Callable[[str], None]

    @property
    def final_attempt(self) -> bool:
        return self.attempt >= self.max_attempts


Handler = Callable[[dict[str, Any], TaskContext], Awaitable[dict[str, Any]]]
HANDLERS: dict[str, Handler] = {}
# Per-kind time limits (seconds); a stuck provider must not hold a slot forever.
TIMEOUTS: dict[str, float] = {"tailor": 900, "linkedin_batch": 1800, "refresh_jobs": 300, "enrich_emails": 900}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return register


@handler("tailor")
async def tailor(payload: dict[str, Any], ctx: TaskContext) -> dict[str, Any]:
    from ..resume.service import run_tailoring

    with SessionLocal() as db:
        return await run_tailoring(
            db,
            resume_id=payload["resume_id"],
            role=payload["role"],
            job_description=payload.get("job_description"),
            job_id=payload.get("job_id"),
            target_score=payload.get("target_score", 90.0),
            max_iterations=payload.get("max_iterations", 4),
            progress=ctx.set_progress,
        )


@handler("send_email")
async def send_email(payload: dict[str, Any], ctx: TaskContext) -> dict[str, Any]:
    from ..outreach.email_sender import send_batch, smtp_configured
    from ..outreach.sending import next_send_time
    from ..routers.applications import advance, track
    from .queue import utcnow

    later = next_send_time()
    if later > utcnow():
        raise Reschedule(later, "Quiet hours")
    if not smtp_configured():
        raise RuntimeError("SMTP is not configured")

    item = SendItem.model_validate(payload["item"])
    attachment = Path(payload["attachment"]) if payload.get("attachment") else None
    [res] = await send_batch(
        [item], attachments=[attachment], attachment_names=[payload.get("attachment_name")]
    )
    with SessionLocal() as db:
        row = db.get(EmailLog, payload["log_id"])
        if res.status != "sent":
            if row is not None:
                row.status = "failed" if ctx.final_attempt else "pending"
                row.error = res.error if ctx.final_attempt else f"Retrying: {res.error}"
            if ctx.final_attempt:
                events.record("email.failed", f"Email to {item.to_email} failed: {res.error}", level="error", db=db)
            db.commit()
            raise RuntimeError(res.error or "send failed")
        if row is not None:
            row.status, row.error = "sent", None
        if item.job_id or (item.company and item.role):
            card = track(
                db, job_id=item.job_id, company=item.company or "", role=item.role or "", tailoring_id=item.tailoring_id
            )
            card.recruiter_email = str(item.to_email)
            advance(card, "contacted")
        events.record(
            "email.sent", f"Emailed {item.to_email}: {item.subject}", db=db, job_id=item.job_id, log_id=payload["log_id"]
        )
        db.commit()
    return {"status": "sent", "to": str(item.to_email)}


@handler("linkedin_batch")
async def linkedin_batch(payload: dict[str, Any], ctx: TaskContext) -> dict[str, Any]:
    from ..outreach import linkedin_sender as li

    items = [LinkedInSendItem.model_validate(i) for i in payload["items"]]
    results = await li.send_batch(items)
    sent = 0
    with SessionLocal() as db:
        for log_id, res in zip(payload["log_ids"], results, strict=False):
            row = db.get(LinkedInLog, log_id)
            if row is not None:
                row.status, row.error = res.status, res.error
            sent += res.status == "sent"
        events.record("linkedin.sent", f"Sent {sent} of {len(items)} LinkedIn DM(s)", db=db)
        db.commit()
    return {"sent": sent, "total": len(items)}


@handler("enrich_emails")
async def enrich_emails(payload: dict[str, Any], ctx: TaskContext) -> dict[str, Any]:
    from ..outreach.job_feed import enrich_jobs

    found = await enrich_jobs(payload.get("job_ids") or [])
    events.record("jobs.enriched", f"Found recruiter emails for {found} job(s)")
    return {"found": found}


@handler("refresh_jobs")
async def refresh_jobs(payload: dict[str, Any], ctx: TaskContext) -> dict[str, Any]:
    from ..outreach.job_feed import run_scheduled_refresh

    new = await run_scheduled_refresh()
    events.record("jobs.fetched", f"Scheduled fetch: {new} new posting(s)")
    return {"new": new}


@handler("backup")
async def backup(payload: dict[str, Any], ctx: TaskContext) -> dict[str, Any]:
    import asyncio

    from ..system.backup import create_backup

    path = await asyncio.to_thread(create_backup)
    state.put(state.LAST_BACKUP, state.now_iso())
    events.record("backup.created", f"Backup saved: {path.name}")
    return {"file": path.name}
