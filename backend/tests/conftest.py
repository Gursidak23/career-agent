"""Shared fixtures: an isolated database for everything that opens its own session."""

import atexit
import os
import shutil
import sys
import tempfile

# Before anything imports the app: tests get their own empty home, so they never
# open the real database, read the real .env (API keys), or write real files.
_TEST_HOME = tempfile.mkdtemp(prefix="career-agent-test-home-")
os.environ["CAREER_HOME"] = _TEST_HOME
atexit.register(shutil.rmtree, _TEST_HOME, ignore_errors=True)

import pytest  # noqa: E402
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db


@pytest.fixture
def system(tmp_path, monkeypatch):
    """(TestClient, session factory, drain) bound to a throwaway database.

    Background code (worker, handlers, event log, state, usage ledger) opens its
    own sessions via SessionLocal, so every app module's SessionLocal is pointed
    at the temp database. drain() runs queued tasks like the worker would.
    """
    from app.main import app

    engine = create_engine(f"sqlite:///{tmp_path / 'sys.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for name, module in list(sys.modules.items()):
        if name.startswith("app") and hasattr(module, "SessionLocal"):
            monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr("app.config.Settings.data_path", property(lambda self: tmp_path), raising=False)
    # Health must not depend on whether this checkout still has pre-migration data.
    monkeypatch.setattr("app.home_migration.legacy_items", lambda: [])

    def _db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    async def drain(include_outward: bool = True, max_tasks: int = 50) -> int:
        from app.tasks import queue
        from app.tasks.worker import run_one

        ran = 0
        while ran < max_tasks:
            with factory() as db:
                task = queue.claim(db, "test-worker", include_outward=include_outward)
            if task is None:
                return ran
            await run_one(task.id)
            ran += 1
        return ran

    app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(app), factory, drain
    finally:
        app.dependency_overrides.pop(get_db, None)
