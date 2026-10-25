"""Persisted system state (key/value), shared by the API and the worker."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..db import SessionLocal
from ..models import SystemState

AUTOMATION_PAUSED = "automation.paused"
WORKER_HEARTBEAT = "worker.heartbeat"
LAST_BACKUP = "backup.last"


def get(key: str, default: Any = None) -> Any:
    with SessionLocal() as db:
        row = db.get(SystemState, key)
        return default if row is None or row.value is None else row.value.get("v", default)


def put(key: str, value: Any) -> None:
    with SessionLocal() as db:
        row = db.get(SystemState, key)
        if row is None:
            db.add(SystemState(key=key, value={"v": value}))
        else:
            row.value = {"v": value}
            row.updated_at = datetime.now(timezone.utc)
        db.commit()


def automation_paused() -> bool:
    return bool(get(AUTOMATION_PAUSED, False))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
