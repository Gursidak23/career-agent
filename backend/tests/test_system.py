"""System layer: task queue, worker, send rules, usage ledger, migrations, backups, ops."""

import zipfile
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.llm.base import LlmError
from app.models import EmailLog, Event, LlmCall, Resume, Tailoring, Task
from app.schemas import ContactInfo, ExperienceItem, ResumeData, SendResult
from app.system import state
from app.tasks import queue
from app.tasks.handlers import HANDLERS, Reschedule


# ------------------------------------------------------------------- queue --
def test_enqueue_dedupes_and_claims_in_order(system):
    _, factory, _ = system
    with factory() as db:
        a = queue.enqueue(db, "noop", {"n": 1}, dedupe_key="k")
        b = queue.enqueue(db, "noop", {"n": 2}, dedupe_key="k")
        later = queue.enqueue(db, "noop", run_at=queue.utcnow() + timedelta(hours=1))
        c = queue.enqueue(db, "noop", {"n": 3})
        db.commit()
        assert a.id == b.id
        first = queue.claim(db, "w")
        second = queue.claim(db, "w")
        assert (first.id, second.id) == (a.id, c.id)
        assert queue.claim(db, "w") is None  # `later` isn't due
        assert first.status == "running" and first.attempts == 1 and later.status == "queued"


def test_fail_backs_off_then_gives_up_and_retry_resets(system):
    _, factory, _ = system
    with factory() as db:
        t = queue.enqueue(db, "noop", max_attempts=2)
        db.commit()
        queue.claim(db, "w")
        assert queue.fail(db, t, "boom") is True and t.status == "queued" and t.run_at > queue.utcnow()
        t.run_at = queue.utcnow()
        db.commit()
        queue.claim(db, "w")
        assert queue.fail(db, t, "boom again") is False and t.status == "failed"
        assert queue.retry(db, t) and t.status == "queued" and t.attempts == 0
        assert queue.cancel(db, t) and t.status == "cancelled"


def test_recover_requeues_tasks_of_a_dead_worker(system):
    _, factory, _ = system
    with factory() as db:
        t = queue.enqueue(db, "noop")
        db.commit()
        queue.claim(db, "dead-worker")
        assert queue.recover(db, all_running=True) == 1
        db.refresh(t)
        assert t.status == "queued" and "Requeued" in t.error


def test_paused_automation_holds_outward_tasks(system):
    _, factory, _ = system
    with factory() as db:
        email = queue.enqueue(db, "send_email", outward=True)
        fetch = queue.enqueue(db, "refresh_jobs")
        db.commit()
        assert queue.claim(db, "w", include_outward=False).id == fetch.id
        assert queue.claim(db, "w", include_outward=False) is None
        assert queue.claim(db, "w").id == email.id


# ------------------------------------------------------------------ worker --
@pytest.mark.asyncio
async def test_worker_runs_retries_reschedules_and_logs_final_failure(system, monkeypatch):
    _, factory, drain = system
    calls = {"ok": 0, "flaky": 0}

    async def ok(payload, ctx):
        calls["ok"] += 1
        ctx.set_progress("halfway")
        return {"echo": payload["x"]}

    async def flaky(payload, ctx):
        calls["flaky"] += 1
        raise RuntimeError("SMTP 421 try later")

    async def later(payload, ctx):
        raise Reschedule(queue.utcnow() + timedelta(hours=8), "Quiet hours")

    monkeypatch.setitem(HANDLERS, "t_ok", ok)
    monkeypatch.setitem(HANDLERS, "t_flaky", flaky)
    monkeypatch.setitem(HANDLERS, "t_later", later)
    with factory() as db:
        a = queue.enqueue(db, "t_ok", {"x": 7})
        b = queue.enqueue(db, "t_flaky", max_attempts=1)
        c = queue.enqueue(db, "t_later")
        db.commit()
    await drain()
    with factory() as db:
        a, b, c = db.get(Task, a.id), db.get(Task, b.id), db.get(Task, c.id)
        assert a.status == "succeeded" and a.result == {"echo": 7} and a.progress == "halfway"
        assert b.status == "failed" and "SMTP 421" in b.error
        assert c.status == "queued" and c.attempts == 0 and c.run_at > queue.utcnow() + timedelta(hours=7)
        assert db.query(Event).filter_by(kind="task.failed").count() == 1


@pytest.mark.asyncio
async def test_schedules_queue_a_backup_once(system, monkeypatch):
    from app.tasks.worker import ensure_schedules

    _, factory, _ = system
    ensure_schedules()
    ensure_schedules()
    with factory() as db:
        assert db.query(Task).filter_by(kind="backup", status="queued").count() == 1


# --------------------------------------------------------------- tailoring --
@pytest.mark.asyncio
async def test_tailor_route_queues_task_that_creates_a_tailoring(system, monkeypatch):
    client, factory, drain = system
    resume = ResumeData(
        contact=ContactInfo(name="Jane"),
        experience=[ExperienceItem(title="Eng", company="Acme", bullets=["Built Python services."])],
    )
    with factory() as db:
        r = Resume(raw_text="x", parsed=resume.model_dump())
        db.add(r)
        db.commit()
        rid = r.id

    from app.resume import service
    from app.resume.ats import score_resume
    from app.resume.tailor import TailorResult

    async def fake_tailor(res, role, jd, **kw):
        return TailorResult(res, score_resume(res, role, jd), 1)

    monkeypatch.setattr(service, "tailor_resume", fake_tailor)
    monkeypatch.setattr(service, "render_files", lambda t, r: None)
    body = {"resume_id": rid, "role": "backend_engineer"}
    t1 = client.post("/api/resume/tailor", json=body)
    t2 = client.post("/api/resume/tailor", json=body)
    assert t1.status_code == 202 and t1.json()["id"] == t2.json()["id"]  # double-click safe
    await drain()
    done = client.get(f"/api/system/tasks/{t1.json()['id']}").json()
    assert done["status"] == "succeeded"
    with factory() as db:
        assert db.get(Tailoring, done["result"]["tailoring_id"]) is not None


# ------------------------------------------------------------- send rules --
def test_daily_cap_schedules_overflow_for_tomorrow(system, monkeypatch):
    client, factory, _ = system
    from app.config import get_settings
    from app.routers import outreach

    monkeypatch.setattr(outreach, "smtp_configured", lambda: True)
    monkeypatch.setattr(get_settings().smtp, "daily_cap", 1)
    items = [{"to_email": f"r{i}@x.com", "subject": "s", "body": "b"} for i in range(2)]
    res = client.post("/api/outreach/send", json={"items": items}).json()
    assert [r["status"] for r in res["results"]] == ["queued", "scheduled"]
    with factory() as db:
        tasks = db.query(Task).filter_by(kind="send_email").order_by(Task.id).all()
        assert tasks[1].run_at - tasks[0].run_at > timedelta(hours=6) and all(t.outward for t in tasks)


def test_quiet_hours_push_sends_to_the_end_of_the_window(monkeypatch):
    from app.config import get_settings
    from app.outreach import sending

    monkeypatch.setattr(get_settings().smtp, "quiet_hours", "22-8")
    local = datetime(2026, 10, 25, 23, 30).astimezone()
    monkeypatch.setattr(sending, "_local_now", lambda: local)
    resume_at = sending.next_send_time().replace(tzinfo=__import__("datetime").timezone.utc).astimezone()
    assert (resume_at.hour, resume_at.day) == (8, 26)


@pytest.mark.asyncio
async def test_failed_send_retries_then_marks_log_failed(system, monkeypatch):
    client, factory, drain = system
    from app.routers import outreach

    async def bad_send(items, **kw):
        return [SendResult(to_email=str(i.to_email), status="failed", error="535 auth failed") for i in items]

    monkeypatch.setattr("app.outreach.email_sender.send_batch", bad_send)
    monkeypatch.setattr("app.outreach.email_sender.smtp_configured", lambda smtp=None: True)
    monkeypatch.setattr(outreach, "smtp_configured", lambda: True)
    client.post("/api/outreach/send", json={"items": [{"to_email": "r@x.com", "subject": "s", "body": "b"}]})
    for _ in range(3):  # each failure backs off; make retries due immediately
        await drain()
        with factory() as db:
            db.execute(text("UPDATE tasks SET run_at = :t WHERE status='queued'"), {"t": queue.utcnow()})
            db.commit()
    with factory() as db:
        log = db.query(EmailLog).one()
        assert log.status == "failed" and "535" in log.error
        assert db.query(Task).one().status == "failed"


# ------------------------------------------------------------ usage ledger --
@pytest.mark.asyncio
async def test_ledger_records_provider_fallbacks_and_paid_fallback_event(system, monkeypatch):
    _, factory, _ = system
    from app.llm import router
    from app.llm.base import report_usage
    from app.llm.fallback import FallbackLlmClient

    class Down:
        name = "gemini"

        async def complete(self, messages, **kw):
            raise LlmError("404 model retired")

    class Paid:
        name = "copilot"

        async def complete(self, messages, **kw):
            report_usage(50, 10, 0.002)
            return '{"ok": true}'

    monkeypatch.setattr(router, "get_llm", lambda: FallbackLlmClient([Down(), Paid()], max_retries=1))
    monkeypatch.setattr(router.get_cache(), "enabled", False)
    monkeypatch.setattr(router, "_paid_fallback_day", None)
    assert await router.complete_json("sys", "hi", purpose="parse") == {"ok": True}
    with factory() as db:
        call = db.query(LlmCall).one()
        assert (call.provider, call.purpose, call.fallbacks, call.credits) == ("copilot", "parse", 1, 0.002)
        assert "404 model retired" in call.error
        assert db.query(Event).filter_by(kind="llm.paid_fallback").count() == 1


# ----------------------------------------------------- migrations & backup --
def test_migrations_run_once_and_fail_orphaned_sends(tmp_path, monkeypatch):
    from app import db as db_module

    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO email_logs (to_email, status, created_at) VALUES ('a@b.c', 'pending', CURRENT_TIMESTAMP)"))
    db_module.init_db()
    db_module.init_db()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM email_logs")).scalar() == "failed"
        assert conn.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar() == len(db_module.MIGRATIONS)


def test_backup_zips_db_and_uploads_and_rotates(tmp_path, monkeypatch):
    import sqlite3

    from app.system import backup

    db_file = tmp_path / "live.db"
    sqlite3.connect(db_file).execute("CREATE TABLE t (x)").connection.commit()
    monkeypatch.setattr(backup, "engine", type("E", (), {"url": type("U", (), {"database": str(db_file)})()})())
    monkeypatch.setattr("app.config.Settings.data_path", property(lambda self: tmp_path))
    (tmp_path / "uploads").mkdir(exist_ok=True)
    (tmp_path / "uploads" / "resume_1.pdf").write_bytes(b"%PDF-1.4")
    for i in range(3):
        (backup.backups_dir() / f"career-agent-2000010{i}-000000.zip").write_bytes(b"old")
    newest = backup.create_backup(keep=2)
    kept = sorted(x.name for x in backup.backups_dir().glob("*.zip"))
    assert kept == ["career-agent-20000102-000000.zip", newest.name]
    with zipfile.ZipFile(newest) as zf:
        assert set(zf.namelist()) == {"career_agent.db", "uploads/resume_1.pdf"}


# -------------------------------------------------------------------- ops --
def test_health_reports_missing_worker_and_backup(system):
    client, _, _ = system
    h = client.get("/api/system/health").json()
    assert h["status"] == "degraded" and not h["worker"]["alive"]
    state.put(state.WORKER_HEARTBEAT, {"at": state.now_iso(), "id": "w", "running": 0})
    state.put(state.LAST_BACKUP, state.now_iso())
    h = client.get("/api/system/health").json()
    assert h["worker"]["alive"] and h["status"] == "ok"


def test_pause_switch_is_recorded(system):
    client, factory, _ = system
    assert client.post("/api/system/automation", json={"paused": True}).json() == {"paused": True}
    assert state.automation_paused()
    with factory() as db:
        assert db.query(Event).filter_by(kind="automation.paused").count() == 1


def test_api_token_required_when_configured(monkeypatch):
    from app import main
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "api_token", "s3cret")
    client = TestClient(main.create_app())
    assert client.get("/api/resume/roles").status_code == 401
    assert client.get("/api/resume/roles", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    client.cookies.set("ca_token", "s3cret")
    assert client.get("/api/resume/roles").status_code == 200
    assert client.get("/health").status_code == 200


def test_prod_mode_serves_built_ui_with_client_routing(tmp_path, monkeypatch):
    from app import main
    from app.config import get_settings

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(get_settings(), "serve_frontend", True)
    monkeypatch.setattr(get_settings(), "frontend_dist", str(tmp_path))
    client = TestClient(main.create_app())
    assert "root" in client.get("/tracker").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/nope").status_code == 404
    assert client.get("/api/resume/roles").status_code == 200


def test_only_one_worker_can_hold_the_lock(tmp_path):
    import subprocess
    import sys

    from app.tasks.worker import acquire_single_worker_lock

    lock_path = tmp_path / "worker.lock"
    held = acquire_single_worker_lock(lock_path)
    # A second process must be refused while this one holds the lock.
    code = (
        "from pathlib import Path; from app.tasks.worker import acquire_single_worker_lock; "
        f"acquire_single_worker_lock(Path({str(lock_path)!r}))"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode != 0 and "already running" in proc.stderr
    held.close()  # released: a new worker may start
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0


def test_cli_refuses_public_bind_without_token(monkeypatch):
    from app import cli
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "api_token", None)
    with pytest.raises(SystemExit, match="Refusing to listen"):
        cli.main(["api", "--host", "0.0.0.0"])

