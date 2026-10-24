"""AgentQL/TinyFish-backed email finder (free tier; needs AGENTQL_API_KEY).

Uses AgentQL's REST query-data endpoint to extract contact emails from a target
page using a natural-language-ish query schema. Falls back to a regex sweep of
the JSON response so it tolerates schema variation.
"""

from __future__ import annotations

import json

import httpx

from .base import EMAIL_RE, EmailCandidate
from .domain import candidate_domains
from ...config import get_settings
from ...logging_setup import get_logger

log = get_logger(__name__)

_QUERY = "{ contacts[] { name email } emails[] }"


def _target_url(domain: str | None, company: str, job_url: str | None) -> str | None:
    if job_url:
        return job_url
    doms = [domain] if domain else candidate_domains(company)[:1]
    for dom in doms:
        if dom:
            return f"https://{dom}/contact"
    return None


def _harvest(data: object) -> set[str]:
    return {m.lower() for m in EMAIL_RE.findall(json.dumps(data))}


class AgentQLFinder:
    name = "agentql"

    async def find(
        self,
        *,
        name: str | None,
        company: str,
        domain: str | None,
        job_url: str | None,
    ) -> list[EmailCandidate]:
        settings = get_settings().emailfinder
        api_key = settings.agentql_api_key
        if not api_key:
            return []

        target = _target_url(domain, company, job_url)
        if not target:
            return []

        payload = {"url": target, "query": _QUERY}
        headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
                resp = await client.post(settings.agentql_endpoint, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001 - API/network errors degrade gracefully
            log.warning("agentql finder failed: %s", exc)
            return []

        emails = _harvest(data)
        return [
            EmailCandidate(email=e, source="agentql", confidence=0.65)
            for e in emails
        ]
