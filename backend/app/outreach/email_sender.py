"""Batch SMTP sender with simple rate limiting (uses the user's configured SMTP).

Designed for personal use with providers like Gmail (use an App Password).
"""

from __future__ import annotations

import asyncio
from email.message import EmailMessage
from pathlib import Path

from ..config import SmtpSettings, get_settings
from ..llm.ratelimit import TokenBucket
from ..logging_setup import get_logger
from ..schemas import SendItem, SendResult

log = get_logger(__name__)


class SmtpNotConfigured(RuntimeError):
    pass


def smtp_configured(smtp: SmtpSettings | None = None) -> bool:
    smtp = smtp or get_settings().smtp
    return bool(smtp.host and smtp.username and smtp.password)


def _build_message(
    item: SendItem,
    smtp: SmtpSettings,
    attachment: Path | None = None,
    attachment_name: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    from_addr = smtp.username or ""
    if smtp.from_name:
        msg["From"] = f"{smtp.from_name} <{from_addr}>"
    else:
        msg["From"] = from_addr
    msg["To"] = str(item.to_email)
    msg["Subject"] = item.subject
    msg.set_content(item.body)
    if attachment and attachment.exists():
        data = attachment.read_bytes()
        subtype_by_ext = {
            ".pdf": "pdf",
            ".docx": "vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        subtype = subtype_by_ext.get(attachment.suffix.lower(), "octet-stream")
        msg.add_attachment(
            data,
            maintype="application",
            subtype=subtype,
            filename=attachment_name or attachment.name,
        )
    return msg


async def send_batch(
    items: list[SendItem],
    *,
    dry_run: bool = False,
    concurrency: int = 5,
    attachments: list[Path | None] | None = None,
    attachment_names: list[str | None] | None = None,
) -> list[SendResult]:
    smtp = get_settings().smtp

    if dry_run:
        return [SendResult(to_email=str(i.to_email), status="dry_run") for i in items]

    if not smtp_configured(smtp):
        raise SmtpNotConfigured(
            "SMTP is not configured. Set CAREER_SMTP__HOST/USERNAME/PASSWORD."
        )

    import aiosmtplib

    bucket = TokenBucket(smtp.per_minute)
    sem = asyncio.Semaphore(max(1, min(concurrency, smtp.per_minute)))
    atts = attachments or [None] * len(items)
    names = attachment_names or [None] * len(items)

    async def _send_one(idx: int, item: SendItem) -> SendResult:
        async with sem:
            await bucket.acquire()
            try:
                message = _build_message(
                    item,
                    smtp,
                    atts[idx] if idx < len(atts) else None,
                    names[idx] if idx < len(names) else None,
                )
                await aiosmtplib.send(
                    message,
                    hostname=smtp.host,
                    port=smtp.port,
                    username=smtp.username,
                    password=smtp.password,
                    start_tls=smtp.use_tls,
                    timeout=30,
                )
                return SendResult(to_email=str(item.to_email), status="sent")
            except Exception as exc:  # noqa: BLE001 - record per-recipient failures
                log.warning("email send failed to %s: %s", item.to_email, exc)
                return SendResult(to_email=str(item.to_email), status="failed", error=str(exc))

    return list(await asyncio.gather(*(_send_one(i, item) for i, item in enumerate(items))))
