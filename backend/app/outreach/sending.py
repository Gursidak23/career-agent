"""Send-time rules: daily cap and quiet hours (local time)."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import EmailLog


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _to_utc_naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def quiet_window() -> tuple[int, int] | None:
    raw = get_settings().smtp.quiet_hours.strip()
    if not raw:
        return None
    try:
        start, end = (int(x) % 24 for x in raw.split("-", 1))
    except ValueError:
        return None
    return (start, end) if start != end else None


def next_send_time(when: datetime | None = None) -> datetime:
    """`when` (UTC naive) moved out of quiet hours, as UTC naive."""
    local = (when.replace(tzinfo=timezone.utc).astimezone() if when else _local_now())
    window = quiet_window()
    if window is None:
        return _to_utc_naive(local)
    start, end = window
    h = local.hour
    quiet = (start <= h or h < end) if start > end else (start <= h < end)
    if not quiet:
        return _to_utc_naive(local)
    resume = local.replace(hour=end, minute=0, second=0, microsecond=0)
    if resume <= local:
        resume += timedelta(days=1)
    return _to_utc_naive(resume)


def emails_counted_today(db: Session) -> int:
    """Sent or waiting-to-send emails created since local midnight."""
    midnight = _to_utc_naive(datetime.combine(_local_now().date(), time(0), tzinfo=_local_now().tzinfo))
    return db.scalar(
        select(func.count(EmailLog.id)).where(
            EmailLog.created_at >= midnight, EmailLog.status.in_(("sent", "pending"))
        )
    ) or 0


def tomorrow_morning() -> datetime:
    local = (_local_now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    return next_send_time(_to_utc_naive(local))
