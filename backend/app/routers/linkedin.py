"""LinkedIn DM endpoints: status, one-time login, async batch send, status list."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..logging_setup import get_logger
from ..models import LinkedInLog
from ..outreach import linkedin_sender as li
from ..schemas import (
    LinkedInBatchRequest,
    LinkedInBatchResponse,
    LinkedInLogOut,
    LinkedInSendItem,
    LinkedInStatus,
    SendResult,
)

router = APIRouter(prefix="/api/linkedin", tags=["linkedin"])
log = get_logger(__name__)


@router.get("/status", response_model=LinkedInStatus)
def status() -> LinkedInStatus:
    cfg = get_settings().linkedin
    return LinkedInStatus(
        enabled=cfg.enabled,
        playwright_available=li.playwright_available(),
        logged_in=li.session_exists(),
    )


async def _run_login() -> None:
    try:
        ok = await li.open_login()
        log.info("linkedin login flow finished: logged_in=%s", ok)
    except Exception as exc:  # noqa: BLE001
        log.warning("linkedin login flow failed: %s", exc)


@router.post("/login")
async def login(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Launch a headed browser so the user can sign in; session is persisted."""
    if not li.playwright_available():
        raise HTTPException(
            status_code=400,
            detail=(
                "Playwright is not installed. Run `pip install playwright` and "
                "`playwright install chromium` to enable LinkedIn automation."
            ),
        )
    background_tasks.add_task(_run_login)
    return {
        "status": "launching",
        "detail": "A browser window is opening. Log in to LinkedIn; the session will be saved.",
    }


async def _run_send(items: list[LinkedInSendItem], log_ids: list[int]) -> None:
    results = await li.send_batch(items)
    db = SessionLocal()
    try:
        for log_id, res in zip(log_ids, results, strict=False):
            row = db.get(LinkedInLog, log_id)
            if row is not None:
                row.status = res.status
                row.error = res.error
        db.commit()
    finally:
        db.close()


@router.post("/send", response_model=LinkedInBatchResponse)
async def send(
    req: LinkedInBatchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> LinkedInBatchResponse:
    if not req.items:
        raise HTTPException(status_code=400, detail="No recipients provided")

    if req.dry_run:
        results = await li.send_batch(req.items, dry_run=True)
        failed = sum(1 for r in results if r.status == "failed")
        return LinkedInBatchResponse(results=results, sent=0, failed=failed, queued=0)

    cfg = get_settings().linkedin
    if not cfg.enabled:
        raise HTTPException(
            status_code=400,
            detail="LinkedIn automation is disabled. Set CAREER_LINKEDIN__ENABLED=true.",
        )
    if not li.playwright_available():
        raise HTTPException(
            status_code=400,
            detail="Playwright is not installed (pip install playwright; playwright install chromium).",
        )
    if not li.session_exists():
        raise HTTPException(
            status_code=400,
            detail="Not logged in. Call POST /api/linkedin/login and sign in first.",
        )

    log_ids: list[int] = []
    for item in req.items:
        row = LinkedInLog(
            profile_url=str(item.profile_url),
            recipient_name=item.recipient_name,
            status="pending",
            message_id=item.message_id,
        )
        db.add(row)
        db.flush()
        log_ids.append(row.id)
    db.commit()

    background_tasks.add_task(_run_send, req.items, log_ids)

    results = [SendResult(to_email=str(i.profile_url), status="queued") for i in req.items]
    return LinkedInBatchResponse(results=results, sent=0, failed=0, queued=len(results))


@router.get("/sends", response_model=list[LinkedInLogOut])
def sends(limit: int = 50, db: Session = Depends(get_db)) -> list[LinkedInLog]:
    return (
        db.query(LinkedInLog)
        .order_by(LinkedInLog.created_at.desc(), LinkedInLog.id.desc())
        .limit(limit)
        .all()
    )
