"""The worker process: runs queued tasks, recurring schedules and a heartbeat.

Run it with `career-agent worker` (or `python -m app.tasks.worker`). It is a
separate process from the API on purpose: restarting or reloading the API never
interrupts a send or a tailoring run. On start it requeues anything a previous
worker left half-done. While automation is paused, outward tasks (emails, DMs)
stay queued; everything else keeps running.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from datetime import timedelta

from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal, init_db
from ..logging_setup import get_logger
from ..models import Task
from ..system import events, state
from . import queue
from .handlers import HANDLERS, TIMEOUTS, Reschedule, TaskContext

log = get_logger(__name__)

HEARTBEAT_SECONDS = 10
SCHEDULE_SECONDS = 60


def schedules() -> list[tuple[str, timedelta, dict]]:
    """Recurring tasks: (kind, interval, payload)."""
    cfg = get_settings()
    out = [("backup", timedelta(hours=24), {})]
    if cfg.scraper.auto_refresh_hours > 0:
        out.append(
            ("refresh_jobs", timedelta(hours=max(0.25, cfg.scraper.auto_refresh_hours)), {"source": cfg.scraper.auto_refresh_source})
        )
    return out


def ensure_schedules() -> None:
    """Queue the next run of each recurring task if none is pending."""
    with SessionLocal() as db:
        for kind, every, payload in schedules():
            pending = db.scalars(
                select(Task).where(Task.kind == kind, Task.status.in_(("queued", "running")))
            ).first()
            if pending is not None:
                continue
            last = db.scalars(
                select(Task)
                .where(Task.kind == kind, Task.finished_at.is_not(None))
                .order_by(Task.finished_at.desc())
            ).first()
            due = max(queue.utcnow(), last.finished_at + every) if last else queue.utcnow()
            queue.enqueue(db, kind, payload, run_at=due, dedupe_key=f"schedule:{kind}:{due:%Y%m%d%H%M}", max_attempts=2)
        db.commit()


async def run_one(task_id: int) -> None:
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            return
        fn = HANDLERS.get(task.kind)
        if fn is None:
            queue.fail(db, task, f"No handler for task kind '{task.kind}'", retry=False)
            return

        def set_progress(text: str) -> None:
            with SessionLocal() as s:
                t = s.get(Task, task_id)
                if t is not None:
                    t.progress = text[:256]
                    s.commit()

        ctx = TaskContext(task.id, task.attempts, task.max_attempts, set_progress)
        try:
            result = await asyncio.wait_for(fn(dict(task.payload or {}), ctx), TIMEOUTS.get(task.kind, 600))
        except Reschedule as r:
            db.refresh(task)
            task.status, task.run_at, task.locked_by = "queued", r.when, None
            task.attempts = max(0, task.attempts - 1)
            task.progress = f"Postponed: {r}"
            db.commit()
            return
        except Exception as exc:  # noqa: BLE001 - every failure is recorded on the task
            db.refresh(task)
            message = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            retrying = queue.fail(db, task, message)
            if not retrying:
                events.record("task.failed", f"{task.kind} #{task.id} failed: {message[:300]}", level="error", task_id=task.id)
            log.warning("task %s #%s failed (%s): %s", task.kind, task.id, "retrying" if retrying else "final", message)
            return
        db.refresh(task)
        queue.succeed(db, task, result)


async def run_worker(*, concurrency: int = 3, poll_seconds: float = 1.0, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    init_db()
    with SessionLocal() as db:
        recovered = queue.recover(db, all_running=True)
    events.record("worker.started", f"Worker {worker_id} started" + (f"; requeued {recovered} interrupted task(s)" if recovered else ""))

    running: set[asyncio.Task] = set()
    loop = asyncio.get_running_loop()
    last_beat = last_schedule = 0.0
    try:
        while not stop.is_set():
            now = loop.time()
            if now - last_beat >= HEARTBEAT_SECONDS:
                state.put(state.WORKER_HEARTBEAT, {"at": state.now_iso(), "id": worker_id, "running": len(running)})
                last_beat = now
            if now - last_schedule >= SCHEDULE_SECONDS:
                try:
                    ensure_schedules()
                except Exception as exc:  # noqa: BLE001
                    log.warning("scheduling failed: %s", exc)
                last_schedule = now

            paused = state.automation_paused()
            while len(running) < concurrency:
                with SessionLocal() as db:
                    task = queue.claim(db, worker_id, include_outward=not paused)
                if task is None:
                    break
                job = asyncio.create_task(run_one(task.id))
                running.add(job)
                job.add_done_callback(running.discard)
            try:
                await asyncio.wait_for(stop.wait(), poll_seconds)
            except TimeoutError:
                pass
    finally:
        if running:
            log.info("waiting for %d running task(s) to finish", len(running))
            await asyncio.wait(running, timeout=60)
        from ..llm.router import aclose_llm

        await aclose_llm()
        state.put(state.WORKER_HEARTBEAT, {"at": state.now_iso(), "id": worker_id, "running": 0, "stopped": True})
        events.record("worker.stopped", f"Worker {worker_id} stopped")


def main() -> None:
    stop = asyncio.Event()

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        await run_worker(stop=stop)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
