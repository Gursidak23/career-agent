"""System operations: health, tasks, activity log, AI usage, backups, pause switch."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..llm.copilot import credits_today
from ..models import Event, LlmCall, Task
from ..schemas import TaskOut
from ..system import events, state
from ..system.backup import backups_dir, list_backups
from ..tasks import enqueue
from ..tasks import queue as task_queue
from ..tasks.api import task_out

router = APIRouter(prefix="/api/system", tags=["system"])

WORKER_STALE_SECONDS = 45


def _parse(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    """One call that says whether every part of the system is working."""
    now = datetime.now(timezone.utc)
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    beat = state.get(state.WORKER_HEARTBEAT) or {}
    beat_at = _parse(beat.get("at"))
    worker_alive = bool(beat_at and not beat.get("stopped") and (now - beat_at).total_seconds() < WORKER_STALE_SECONDS)
    last_backup = _parse(state.get(state.LAST_BACKUP))
    day_ago = (now - timedelta(days=1)).replace(tzinfo=None)
    counts = dict(db.execute(select(Task.status, func.count(Task.id)).group_by(Task.status)).all())
    failed_24h = db.scalar(select(func.count(Task.id)).where(Task.status == "failed", Task.finished_at >= day_ago)) or 0
    llm_fail_24h = db.scalar(select(func.count(LlmCall.id)).where(LlmCall.ok.is_(False), LlmCall.created_at >= day_ago)) or 0
    budget = get_settings().llm.copilot_daily_credit_budget
    problems = []
    if not db_ok:
        problems.append("Database unreachable")
    if not worker_alive:
        problems.append("Worker not running: emails, tailoring and schedules are waiting")
    if not last_backup or (now - last_backup) > timedelta(days=2):
        problems.append("No backup in the last 2 days")
    if failed_24h:
        problems.append(f"{failed_24h} task(s) failed in the last 24h")
    if llm_fail_24h:
        problems.append(f"{llm_fail_24h} AI call(s) failed in the last 24h")
    return {
        "status": "ok" if not problems else "degraded",
        "problems": problems,
        "api": True,
        "database": db_ok,
        "worker": {"alive": worker_alive, "last_heartbeat": beat.get("at"), "running": beat.get("running", 0)},
        "queue": {"queued": counts.get("queued", 0), "running": counts.get("running", 0), "failed_24h": failed_24h},
        "automation_paused": state.automation_paused(),
        "last_backup": last_backup.isoformat() if last_backup else None,
        "copilot_credits_today": round(credits_today(), 4),
        "copilot_daily_budget": budget,
    }


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(status: str | None = None, limit: int = 50, db: Session = Depends(get_db)) -> list[TaskOut]:
    stmt = select(Task).order_by(Task.id.desc()).limit(min(limit, 500))
    if status:
        stmt = stmt.where(Task.status == status)
    return [task_out(t) for t in db.scalars(stmt)]


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)) -> TaskOut:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task_out(task)


@router.post("/tasks/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: int, db: Session = Depends(get_db)) -> TaskOut:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task_queue.cancel(db, task):
        raise HTTPException(status_code=409, detail=f"Only queued tasks can be cancelled (this one is {task.status})")
    events.record("task.cancelled", f"Cancelled {task.kind} #{task.id}", task_id=task.id)
    return task_out(task)


@router.post("/tasks/{task_id}/retry", response_model=TaskOut)
def retry_task(task_id: int, db: Session = Depends(get_db)) -> TaskOut:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task_queue.retry(db, task):
        raise HTTPException(status_code=409, detail=f"Only failed or cancelled tasks can be retried (this one is {task.status})")
    events.record("task.retried", f"Retrying {task.kind} #{task.id}", task_id=task.id)
    return task_out(task)


@router.get("/events")
def list_events(limit: int = 100, level: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Event).order_by(Event.id.desc()).limit(min(limit, 500))
    if level:
        stmt = stmt.where(Event.level == level)
    return [
        {"id": e.id, "created_at": e.created_at, "kind": e.kind, "level": e.level, "message": e.message, "data": e.data}
        for e in db.scalars(stmt)
    ]


@router.get("/usage")
def usage(days: int = 7, db: Session = Depends(get_db)) -> dict:
    """AI calls by provider: volume, failures, latency, tokens and Copilot credits."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)
    rows = db.execute(
        select(
            LlmCall.provider,
            func.count(LlmCall.id),
            func.sum(case((LlmCall.ok.is_(True), 1), else_=0)),
            func.avg(LlmCall.latency_ms),
            func.sum(LlmCall.input_tokens),
            func.sum(LlmCall.output_tokens),
            func.sum(LlmCall.credits),
            func.sum(LlmCall.fallbacks),
        )
        .where(LlmCall.created_at >= since)
        .group_by(LlmCall.provider)
    ).all()
    by_purpose = dict(
        db.execute(
            select(LlmCall.purpose, func.count(LlmCall.id)).where(LlmCall.created_at >= since).group_by(LlmCall.purpose)
        ).all()
    )
    recent_errors = [
        {"created_at": c.created_at, "purpose": c.purpose, "error": (c.error or "")[:300]}
        for c in db.scalars(
            select(LlmCall).where(LlmCall.error.is_not(None)).order_by(LlmCall.id.desc()).limit(5)
        )
    ]
    return {
        "days": days,
        "providers": [
            {
                "provider": p or "(all failed)",
                "calls": n,
                "ok": int(ok or 0),
                "avg_latency_ms": int(avg or 0),
                "input_tokens": int(tin or 0),
                "output_tokens": int(tout or 0),
                "credits": round(float(cr or 0), 4),
                "fallbacks": int(fb or 0),
            }
            for p, n, ok, avg, tin, tout, cr, fb in rows
        ],
        "by_purpose": by_purpose,
        "copilot_credits_today": round(credits_today(), 4),
        "copilot_daily_budget": get_settings().llm.copilot_daily_credit_budget,
        "recent_errors": recent_errors,
    }


@router.get("/backups")
def backups() -> list[dict]:
    return list_backups()


@router.post("/backups", response_model=TaskOut)
def backup_now(db: Session = Depends(get_db)) -> TaskOut:
    task = enqueue(db, "backup", {}, dedupe_key="backup:manual", active_only=True, max_attempts=1)
    db.commit()
    return task_out(task)


@router.get("/backups/{name}")
def download_backup(name: str) -> FileResponse:
    path = backups_dir() / name
    if not name.startswith("career-agent-") or not name.endswith(".zip") or path.parent != backups_dir() or not path.exists():
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path, media_type="application/zip", filename=name)


class PauseRequest(BaseModel):
    paused: bool


@router.post("/automation")
def set_automation(req: PauseRequest) -> dict:
    """Kill switch: while paused, no email or DM leaves the system (they stay queued)."""
    state.put(state.AUTOMATION_PAUSED, req.paused)
    events.record(
        "automation.paused" if req.paused else "automation.resumed",
        "Outgoing emails and DMs paused" if req.paused else "Outgoing emails and DMs resumed",
        level="warn" if req.paused else "info",
    )
    return {"paused": req.paused}
