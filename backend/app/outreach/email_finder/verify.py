"""Email verification: MX lookup + optional SMTP RCPT probe (graded).

Verification is best-effort: outbound SMTP (port 25) is frequently blocked and
catch-all domains accept any address, so we return a grade rather than a hard
yes/no:
  - verified: SMTP accepted the RCPT and the domain is not catch-all
  - mx_only:  the domain has MX records (mail is plausible) but RCPT not confirmed
  - unverified: no MX / lookup failed
"""

from __future__ import annotations

import asyncio
import contextlib

from ...config import get_settings
from ...logging_setup import get_logger
from .base import GRADE_MX_ONLY, GRADE_UNVERIFIED, GRADE_VERIFIED

log = get_logger(__name__)

_mx_cache: dict[str, list[str]] = {}


def _domain_of(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower()


def _resolve_mx_sync(domain: str) -> list[str]:
    if domain in _mx_cache:
        return _mx_cache[domain]
    hosts: list[str] = []
    try:
        import dns.resolver  # from dnspython

        answers = dns.resolver.resolve(domain, "MX")
        records = sorted(answers, key=lambda r: r.preference)
        hosts = [str(r.exchange).rstrip(".") for r in records]
    except Exception:  # noqa: BLE001 - no MX / resolver error
        # Fall back to an A record check so domains without explicit MX still pass.
        try:
            import dns.resolver

            dns.resolver.resolve(domain, "A")
            hosts = [domain]
        except Exception:  # noqa: BLE001
            hosts = []
    _mx_cache[domain] = hosts
    return hosts


async def has_mx(domain: str) -> bool:
    hosts = await asyncio.to_thread(_resolve_mx_sync, domain)
    return bool(hosts)


def _smtp_probe_sync(email: str, mx_hosts: list[str], from_email: str) -> str:
    """Return a verification grade using an SMTP RCPT probe."""
    import smtplib

    domain = _domain_of(email)
    for host in mx_hosts[:2]:
        try:
            server = smtplib.SMTP(timeout=8)
            server.connect(host, 25)
            server.helo(from_email.split("@")[-1] or "example.com")
            server.mail(from_email)
            code, _ = server.rcpt(email)
            # Catch-all detection: probe a random address.
            catchall_code, _ = server.rcpt(f"zz-nonexistent-9182@{domain}")
            with contextlib.suppress(Exception):
                server.quit()
            if code in (250, 251):
                if catchall_code in (250, 251):
                    return GRADE_MX_ONLY  # catch-all: cannot confirm this address
                return GRADE_VERIFIED
            return GRADE_MX_ONLY
        except Exception as exc:  # noqa: BLE001 - port blocked / greylisted / refused
            log.info("smtp probe failed for %s via %s: %s", email, host, exc)
            continue
    return GRADE_MX_ONLY


async def verify_email(email: str) -> str:
    """Return a verification grade for a single address."""
    settings = get_settings().emailfinder
    domain = _domain_of(email)
    mx_hosts = await asyncio.to_thread(_resolve_mx_sync, domain)
    if not mx_hosts:
        return GRADE_UNVERIFIED
    if not settings.smtp_verify:
        return GRADE_MX_ONLY
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_smtp_probe_sync, email, mx_hosts, settings.verify_from_email),
            timeout=settings.timeout_seconds,
        )
    except (TimeoutError, asyncio.TimeoutError):
        return GRADE_MX_ONLY
