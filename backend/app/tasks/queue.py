"""SQLite-backed task queue.

Tasks are rows: enqueue writes one, the worker claims it atomically
(UPDATE ... RETURNING), runs it, and records the result. A failure retries with
exponential backoff until max_attempts. A dedupe_key makes enqueueing
idempotent: while a task with the same key is queued, running or succeeded, the
existing one is returned instead of a duplicate.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..models import Task

RETRY_BASE_SECONDS = 30
LEASE_MINUTES = 30  # a running task untouched this long belonged to a dead worker


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue(
    db: Session,
    kind: str,
    payload: dict[str, Any] | None = None,
    *,
    dedupe_key: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 3,
    outward: bool = False,
    active_only: bool = False,
) -> Task:
    """Queue a task. With a dedupe_key, an existing queued/running (and, unless
    active_only, succeeded) task with that key is returned instead."""
    if dedupe_key:
        statuses = ("queued", "running") if active_only else ("queued", "running", "succeeded")
        existing = db.scalars(
            select(Task).where(Task.dedupe_key == dedupe_key, Task.status.in_(statuses))
        ).first()
        if existing is not None:
            return existing
    task = Task(
        kind=kind,
        payload=payload or {},
        dedupe_key=dedupe_key,
        run_at=run_at or utcnow(),
        max_attempts=max_attempts,
        outward=outward,
    )
    db.add(task)
    db.flush()
    return task


def claim(db: Session, worker_id: str, *, include_outward: bool = True) -> Task | None:
    """Atomically take the next due task (oldest first)."""
    outward_clause = "" if include_outward else "AND outward = 0 "
    row = db.execute(
        text(
            "UPDATE tasks SET status='running', locked_by=:w, locked_at=:now, "
            "attempts=attempts+1, updated_at=:now "
            "WHERE id = (SELECT id FROM tasks WHERE status='queued' AND run_at <= :now "
            f"{outward_clause}ORDER BY run_at, id LIMIT 1) RETURNING id"
        ),
        {"w": worker_id, "now": utcnow()},
    ).first()
    db.commit()
    # The UPDATE bypassed the ORM: reload so a cached copy can't hide the change.
    return db.get(Task, row[0], populate_existing=True) if row else None


def succeed(db: Session, task: Task, result: dict[str, Any] | None = None) -> None:
    task.status, task.result, task.error = "succeeded", result or {}, None
    task.finished_at = utcnow()
    task.locked_by = None
    db.commit()


def fail(db: Session, task: Task, error: str, *, retry: bool = True) -> bool:
    """Record a failure. Returns True if the task will be retried."""
    task.error = error[:4000]
    task.locked_by = None
    if retry and task.attempts < task.max_attempts:
        task.status = "queued"
        task.run_at = utcnow() + timedelta(seconds=RETRY_BASE_SECONDS * 2 ** (task.attempts - 1))
        db.commit()
        return True
    task.status = "failed"
    task.finished_at = utcnow()
    db.commit()
    return False


def recover(db: Session, *, all_running: bool = False) -> int:
    """Requeue tasks whose worker died. On worker start every 'running' task is orphaned."""
    cutoff = utcnow() - timedelta(minutes=LEASE_MINUTES)
    stmt = select(Task).where(Task.status == "running")
    if not all_running:
        stmt = stmt.where(Task.locked_at < cutoff)
    n = 0
    for task in db.scalars(stmt):
        task.status, task.locked_by, task.run_at = "queued", None, utcnow()
        task.error = "Requeued after the worker stopped mid-task"
        n += 1
    db.commit()
    return n


def cancel(db: Session, task: Task) -> bool:
    if task.status != "queued":
        return False
    task.status, task.finished_at = "cancelled", utcnow()
    db.commit()
    return True


def retry(db: Session, task: Task) -> bool:
    if task.status not in ("failed", "cancelled"):
        return False
    task.status, task.run_at, task.error = "queued", utcnow(), None
    task.attempts = 0
    task.finished_at = None
    db.commit()
    return True
