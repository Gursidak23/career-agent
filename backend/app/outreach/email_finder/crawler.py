"""Lightweight async site crawler that scrapes emails from a company site.

Fetches the homepage plus a few likely contact pages (and the job URL) with
bounded concurrency using httpx, then extracts addresses with a regex. No API
key required.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin

import httpx

from .base import EMAIL_RE, EmailCandidate
from ...config import get_settings
from ...logging_setup import get_logger

log = get_logger(__name__)

_CONTACT_PATHS = ["", "/contact", "/contact-us", "/about", "/about-us", "/team", "/careers", "/jobs"]
_MAILTO_RE = re.compile(r"mailto:([^\"'?>\s]+)", re.IGNORECASE)
# Addresses we don't want to surface (generic/no-reply/asset filenames).
_SKIP_LOCAL = {"noreply", "no-reply", "donotreply", "example", "email", "your"}
_ASSET_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")


def _clean(email: str) -> str | None:
    email = email.strip().strip(".,;:<>()[]\"'").lower()
    if email.endswith(_ASSET_EXT):
        return None
    local = email.split("@")[0]
    if local in _SKIP_LOCAL or "@" not in email:
        return None
    return email


def _extract(text: str) -> set[str]:
    found: set[str] = set()
    for raw in _MAILTO_RE.findall(text):
        cleaned = _clean(raw)
        if cleaned:
            found.add(cleaned)
    for raw in EMAIL_RE.findall(text):
        cleaned = _clean(raw)
        if cleaned:
            found.add(cleaned)
    return found


def _on_domain(email: str, domain: str | None) -> bool:
    if not domain:
        return True
    base = ".".join(domain.split(".")[-2:])
    return email.endswith("@" + domain) or email.endswith("." + base) or email.endswith("@" + base)


class CrawlerFinder:
    name = "crawler"

    async def find(
        self,
        *,
        name: str | None,
        company: str,
        domain: str | None,
        job_url: str | None,
    ) -> list[EmailCandidate]:
        settings = get_settings().emailfinder
        urls = self._seed_urls(domain, job_url, settings.crawler_max_pages)
        if not urls:
            return []

        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(
            timeout=settings.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CareerAgent/1.0)"},
        ) as client:
            results = await asyncio.gather(
                *(self._fetch(client, url, sem) for url in urls),
                return_exceptions=True,
            )

        emails: set[str] = set()
        for res in results:
            if isinstance(res, set):
                emails |= res

        candidates: list[EmailCandidate] = []
        for email in emails:
            on_domain = _on_domain(email, domain)
            candidates.append(
                EmailCandidate(
                    email=email,
                    source="crawler",
                    # On-domain addresses scraped from the site are high signal.
                    confidence=0.8 if on_domain else 0.5,
                )
            )
        return candidates

    def _seed_urls(self, domain: str | None, job_url: str | None, max_pages: int) -> list[str]:
        urls: list[str] = []
        if job_url:
            urls.append(job_url)
        if domain:
            for path in _CONTACT_PATHS:
                urls.append(urljoin(f"https://{domain}", path))
        # De-dupe preserving order, then cap.
        seen: set[str] = set()
        ordered = [u for u in urls if not (u in seen or seen.add(u))]
        return ordered[:max_pages]

    async def _fetch(self, client: httpx.AsyncClient, url: str, sem: asyncio.Semaphore) -> set[str]:
        async with sem:
            try:
                resp = await client.get(url)
                if resp.status_code >= 400 or "text" not in resp.headers.get("content-type", "text"):
                    return set()
                return _extract(resp.text)
            except Exception as exc:  # noqa: BLE001 - network failures are expected
                log.info("crawler fetch failed for %s: %s", url, exc)
                return set()
