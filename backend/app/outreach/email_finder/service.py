"""Orchestrate the email finder provider chain.

Runs enabled providers in priority order, aggregates and de-dupes candidates,
verifies them (MX/SMTP graded), ranks the results, and short-circuits once a
verified address is found (when configured).
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from ...config import get_settings
from ...logging_setup import get_logger
from .agentql import AgentQLFinder
from .apify import ApifyFinder
from .base import GRADE_VERIFIED, EmailCandidate, EmailFinder
from .crawler import CrawlerFinder
from .domain import resolve_domain
from .patterns import PatternFinder
from .verify import verify_email

log = get_logger(__name__)


class EmailFinderService:
    def __init__(self) -> None:
        self._verify_cache: dict[str, str] = {}

    def _chain(self) -> list[EmailFinder]:
        """Enabled providers, strongest signal first."""
        s = get_settings().emailfinder
        chain: list[EmailFinder] = []
        if s.crawler_enabled:
            chain.append(CrawlerFinder())
        if s.agentql_api_key:
            chain.append(AgentQLFinder())
        if s.apify_token:
            chain.append(ApifyFinder())
        if s.pattern_enabled:
            chain.append(PatternFinder())
        return chain

    async def find(
        self,
        *,
        name: str | None = None,
        company: str,
        domain: str | None = None,
        job_url: str | None = None,
    ) -> list[EmailCandidate]:
        settings = get_settings().emailfinder
        resolved = resolve_domain(company, domain, job_url)
        merged: dict[str, EmailCandidate] = {}

        for finder in self._chain():
            try:
                found = await finder.find(
                    name=name, company=company, domain=resolved, job_url=job_url
                )
            except Exception as exc:  # noqa: BLE001 - one provider must not break the chain
                log.warning("email finder %s errored: %s", finder.name, exc)
                found = []

            self._merge(merged, found)
            await self._verify_all(merged)

            if settings.stop_on_verified and any(
                c.verified == GRADE_VERIFIED for c in merged.values()
            ):
                break

        ranked = sorted(merged.values(), key=lambda c: c.sort_key(), reverse=True)
        return ranked[: settings.max_candidates]

    def _merge(self, merged: dict[str, EmailCandidate], found: list[EmailCandidate]) -> None:
        for cand in found:
            key = cand.email.lower()
            existing = merged.get(key)
            if existing is None:
                merged[key] = cand
            else:
                # Keep the strongest signal; remember the name if we learn it.
                existing.confidence = max(existing.confidence, cand.confidence)
                existing.name = existing.name or cand.name
                if cand.grade_rank > existing.grade_rank:
                    existing.verified = cand.verified

    async def _verify_all(self, merged: dict[str, EmailCandidate]) -> None:
        pending = [c for c in merged.values() if c.email not in self._verify_cache]
        if not pending:
            for c in merged.values():
                c.verified = self._verify_cache.get(c.email, c.verified)
            return
        grades = await asyncio.gather(*(verify_email(c.email) for c in pending))
        for cand, grade in zip(pending, grades):
            self._verify_cache[cand.email] = grade
        for c in merged.values():
            c.verified = self._verify_cache.get(c.email, c.verified)


@lru_cache(maxsize=1)
def get_service() -> EmailFinderService:
    return EmailFinderService()


def available_providers() -> list[tuple[str, bool]]:
    """(provider_name, configured/enabled) for the settings status endpoint."""
    s = get_settings().emailfinder
    return [
        ("crawler", s.crawler_enabled),
        ("pattern", s.pattern_enabled),
        ("apify", bool(s.apify_token)),
        ("agentql", bool(s.agentql_api_key)),
        ("smtp_verify", s.smtp_verify),
    ]
