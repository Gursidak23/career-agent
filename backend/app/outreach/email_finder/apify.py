"""Apify-backed email finder (free tier; dormant unless APIFY_TOKEN is set).

Runs an Apify actor synchronously via the REST API and harvests any email
addresses from its dataset output. The default actor extracts page content; we
regex emails out of the returned items, so this works with a range of generic
scraping/extraction actors on the free tier.
"""

from __future__ import annotations

import json

import httpx

from .base import EMAIL_RE, EmailCandidate
from .domain import candidate_domains
from ...config import get_settings
from ...logging_setup import get_logger

log = get_logger(__name__)


def _start_urls(domain: str | None, company: str, job_url: str | None) -> list[str]:
    urls: list[str] = []
    if job_url:
        urls.append(job_url)
    doms = [domain] if domain else candidate_domains(company)[:1]
    for dom in doms:
        if dom:
            urls.append(f"https://{dom}")
            urls.append(f"https://{dom}/contact")
    return urls


def _harvest(items: object) -> set[str]:
    blob = json.dumps(items)
    return {m.lower() for m in EMAIL_RE.findall(blob)}


class ApifyFinder:
    name = "apify"

    async def find(
        self,
        *,
        name: str | None,
        company: str,
        domain: str | None,
        job_url: str | None,
    ) -> list[EmailCandidate]:
        settings = get_settings().emailfinder
        token = settings.apify_token
        if not token:
            return []

        start_urls = _start_urls(domain, company, job_url)
        if not start_urls:
            return []

        actor = settings.apify_actor.replace("/", "~")
        url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
        payload = {"startUrls": [{"url": u} for u in start_urls], "maxRequestsPerCrawl": 5}

        try:
            async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
                resp = await client.post(url, params={"token": token}, json=payload)
                resp.raise_for_status()
                items = resp.json()
        except Exception as exc:  # noqa: BLE001 - API/network errors degrade gracefully
            log.warning("apify finder failed: %s", exc)
            return []

        emails = _harvest(items)
        return [
            EmailCandidate(email=e, source="apify", confidence=0.6)
            for e in emails
        ]
