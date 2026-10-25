"""Append-only event log: an audit trail of what the system did and why."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..logging_setup import get_logger
from ..models import Event

log = get_logger(__name__)


def record(kind: str, message: str, *, level: str = "info", db: Session | None = None, **data: Any) -> None:
    """Write one event. Never raises: auditing must not break the action itself."""
    getattr(log, "warning" if level in ("warn", "error") else "info")("%s: %s", kind, message)
    own = db is None
    session = SessionLocal() if own else db
    try:
        session.add(Event(kind=kind, level=level, message=message[:2000], data=data or None))
        if own:
            session.commit()
        else:
            session.flush()
    except Exception as exc:  # noqa: BLE001
        log.warning("could not record event %s: %s", kind, exc)
    finally:
        if own:
            session.close()
