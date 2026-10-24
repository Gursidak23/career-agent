"""Aggregator that fans out to all real job sources and merges the results.

Each underlying source is independent: if one is down or rate-limited, the others
still contribute. Results are de-duped on (company, title).
"""

from __future__ import annotations

from ...logging_setup import get_logger
from .arbeitnow import ArbeitnowSource
from .base import JobRecord
from .hackernews import HackerNewsSource
from .remoteok import RemoteOkSource
from .remotive import RemotiveSource

log = get_logger(__name__)


class AggregateSource:
    name = "all"

    def __init__(self) -> None:
        self._sources = [
            RemotiveSource(),
            RemoteOkSource(),
            ArbeitnowSource(),
            HackerNewsSource(),
        ]

    def fetch(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        limit: int = 25,
    ) -> list[JobRecord]:
        # Split the budget across sources, with a small floor so each contributes.
        per_source = max(5, limit // len(self._sources))
        seen: set[tuple[str, str]] = set()
        merged: list[JobRecord] = []
        errors: list[str] = []

        for source in self._sources:
            try:
                records = source.fetch(query=query, location=location, limit=per_source)
            except RuntimeError as exc:
                errors.append(f"{source.name}: {exc}")
                continue
            for rec in records:
                key = (rec.company.strip().lower(), rec.title.strip().lower())
                if key in seen or not rec.company:
                    continue
                seen.add(key)
                merged.append(rec)

        if not merged and errors:
            raise RuntimeError("All job sources failed. " + " | ".join(errors))
        return merged[:limit]
