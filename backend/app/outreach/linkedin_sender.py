"""LinkedIn DM sending via Playwright with a persistent login session.

Real automation against your own logged-in LinkedIn account:

  1. Call ``open_login()`` once (headed browser) and sign in manually. The
     session is saved to ``user_data_dir`` and reused afterwards.
  2. ``send_batch()`` reuses that session (headless) to open each recipient's
     profile, type the message, and send it — throttled to look human.

Everything degrades gracefully: if Playwright (or its browser) isn't installed,
the functions report unavailability instead of raising at import time. LinkedIn's
DOM changes over time, so the selectors below are best-effort with fallbacks.

NOTE: Automating LinkedIn can violate its Terms of Service. Use conservatively,
for personal outreach only, at low volume.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from ..config import get_settings
from ..llm.ratelimit import TokenBucket
from ..logging_setup import get_logger
from ..schemas import LinkedInSendItem, SendResult

log = get_logger(__name__)

_PROFILE_RE = re.compile(r"^https?://([\w-]+\.)?linkedin\.com/in/", re.IGNORECASE)


def playwright_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def session_exists() -> bool:
    """Best-effort check that a login session has been persisted."""
    cfg = get_settings().linkedin
    p = Path(cfg.user_data_dir)
    # A logged-in Chromium profile has a populated "Default" directory.
    return p.exists() and any(p.iterdir())


def is_valid_profile_url(url: str) -> bool:
    return bool(_PROFILE_RE.match(url.strip()))


async def _open_context(playwright, *, headless: bool):
    cfg = get_settings().linkedin
    Path(cfg.user_data_dir).mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, object] = {
        "user_data_dir": cfg.user_data_dir,
        "headless": headless,
        "viewport": {"width": 1280, "height": 900},
    }
    if cfg.browser_channel:
        kwargs["channel"] = cfg.browser_channel
    return await playwright.chromium.launch_persistent_context(**kwargs)


async def open_login(wait_seconds: float = 180.0) -> bool:
    """Launch a headed browser so the user can log in; persist the session.

    Returns True once the LinkedIn feed is reached (i.e. login succeeded).
    """
    if not playwright_available():
        raise RuntimeError(
            "Playwright is not installed. Run `pip install playwright` and "
            "`playwright install chromium` to enable LinkedIn automation."
        )
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        try:
            context = await _open_context(p, headless=False)
        except Exception as exc:  # noqa: BLE001 - browser binary missing, etc.
            raise RuntimeError(
                f"Could not launch a browser for LinkedIn login: {exc}. "
                "Did you run `playwright install chromium`?"
            ) from exc
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            # Poll until we land on the feed (logged in) or time out.
            deadline = asyncio.get_event_loop().time() + wait_seconds
            while asyncio.get_event_loop().time() < deadline:
                if "/feed" in page.url:
                    return True
                await asyncio.sleep(2)
            return "/feed" in page.url
        finally:
            await context.close()


async def _send_one(page, item: LinkedInSendItem, timeout_ms: int) -> SendResult:
    target = str(item.profile_url)
    try:
        await page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)

        # Open the message composer (the profile "Message" button).
        msg_button = page.get_by_role("button", name=re.compile(r"message", re.IGNORECASE))
        await msg_button.first.click(timeout=timeout_ms)

        # The composer is a contenteditable; try a few known selectors.
        editor = page.locator(
            "div.msg-form__contenteditable[contenteditable='true'], "
            "div[aria-label='Write a message…'], "
            "div[role='textbox'][contenteditable='true']"
        ).first
        await editor.wait_for(state="visible", timeout=timeout_ms)
        await editor.click()
        await editor.fill(item.message)

        # Click the Send button (fall back to Ctrl+Enter).
        send_btn = page.locator(
            "button.msg-form__send-button, button[type='submit']:has-text('Send')"
        ).first
        try:
            await send_btn.click(timeout=5000)
        except Exception:  # noqa: BLE001
            await page.keyboard.press("Control+Enter")

        return SendResult(to_email=target, status="sent")
    except Exception as exc:  # noqa: BLE001 - record per-recipient failure
        log.warning("linkedin send failed for %s: %s", target, exc)
        return SendResult(to_email=target, status="failed", error=str(exc))


async def send_batch(
    items: list[LinkedInSendItem],
    *,
    dry_run: bool = False,
) -> list[SendResult]:
    """Send DMs to each recipient, throttled. Validates URLs up front."""
    cfg = get_settings().linkedin

    # Validate profile URLs regardless of mode.
    def _check(it: LinkedInSendItem) -> SendResult | None:
        if not is_valid_profile_url(str(it.profile_url)):
            return SendResult(
                to_email=str(it.profile_url),
                status="failed",
                error="Not a valid LinkedIn profile URL (expected .../in/<handle>).",
            )
        return None

    if dry_run:
        return [
            _check(it) or SendResult(to_email=str(it.profile_url), status="dry_run")
            for it in items
        ]

    if not cfg.enabled:
        raise RuntimeError(
            "LinkedIn automation is disabled. Set CAREER_LINKEDIN__ENABLED=true and "
            "log in via /api/linkedin/login first."
        )
    if not playwright_available():
        raise RuntimeError(
            "Playwright is not installed. Run `pip install playwright` and "
            "`playwright install chromium`."
        )

    from playwright.async_api import async_playwright

    bucket = TokenBucket(cfg.per_minute)
    timeout_ms = int(cfg.timeout_seconds * 1000)
    results: list[SendResult] = []

    async with async_playwright() as p:
        try:
            context = await _open_context(p, headless=cfg.headless)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Could not launch browser: {exc}") from exc
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            for item in items:
                invalid = _check(item)
                if invalid is not None:
                    results.append(invalid)
                    continue
                await bucket.acquire()
                results.append(await _send_one(page, item, timeout_ms))
                # Human-like pause between sends.
                await asyncio.sleep(cfg.min_delay_seconds)
        finally:
            await context.close()
    return results
