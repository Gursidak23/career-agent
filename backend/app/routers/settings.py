"""Settings/status endpoint: which providers + integrations are configured."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter

from ..config import env_file_path, get_settings, shadowed_env_vars
from ..llm import ChatMessage, LlmError
from ..llm.router import available_providers, get_llm
from ..outreach.email_finder import available_providers as email_providers
from ..outreach.email_sender import smtp_configured
from ..outreach.linkedin_sender import playwright_available
from ..resume.latex import tectonic_available
from ..resume.roles import role_keys
from ..schemas import ConnectionTest, EmailProviderStatus, ProviderStatus, SettingsStatus

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/status", response_model=SettingsStatus)
def status() -> SettingsStatus:
    providers = [
        ProviderStatus(name=name, configured=configured, model=model)
        for name, configured, model in available_providers()
    ]
    return SettingsStatus(
        providers=providers,
        smtp_configured=smtp_configured(),
        tectonic_available=tectonic_available(),
        roles=role_keys(),
        email_providers=[
            EmailProviderStatus(name=name, enabled=enabled)
            for name, enabled in email_providers()
        ],
        linkedin_enabled=get_settings().linkedin.enabled,
        linkedin_available=playwright_available(),
        env_overrides=shadowed_env_vars(),
        env_file=str(env_file_path()),
        company_boards=len(get_settings().scraper.company_boards),
        auto_refresh_hours=get_settings().scraper.auto_refresh_hours,
        digest_email=get_settings().scraper.digest_email,
    )


async def _timed(name: str, coro, timeout: float) -> ConnectionTest:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout)
    except Exception as exc:  # noqa: BLE001 - report any failure to the UI
        return ConnectionTest(name=name, ok=False, detail=str(exc)[:300] or type(exc).__name__)
    return ConnectionTest(name=name, ok=True, latency_ms=int((time.perf_counter() - start) * 1000))


@router.post("/test-llm", response_model=list[ConnectionTest])
async def test_llm() -> list[ConnectionTest]:
    """Ping every configured provider directly (no fallback, no cache)."""
    try:
        clients = get_llm().clients
    except LlmError as exc:
        return [ConnectionTest(name="llm", ok=False, detail=str(exc))]
    msgs = [ChatMessage("system", "Reply with the word ok."), ChatMessage("user", "ping")]
    return list(
        await asyncio.gather(
            *(
                _timed(c.name, c.complete(msgs, temperature=0.0, max_tokens=256), 120)
                for c in clients
            )
        )
    )


@router.post("/test-smtp", response_model=ConnectionTest)
async def test_smtp() -> ConnectionTest:
    """Log in to the SMTP server and disconnect; no email is sent."""
    smtp = get_settings().smtp
    if not smtp_configured(smtp):
        return ConnectionTest(
            name="smtp", ok=False, detail="Set CAREER_SMTP__USERNAME and CAREER_SMTP__PASSWORD."
        )
    import aiosmtplib

    async def _login() -> None:
        client = aiosmtplib.SMTP(
            hostname=smtp.host, port=smtp.port, start_tls=smtp.use_tls, timeout=20
        )
        await client.connect()
        try:
            await client.login(smtp.username, smtp.password)
        finally:
            await client.quit()

    return await _timed("smtp", _login(), 30)
