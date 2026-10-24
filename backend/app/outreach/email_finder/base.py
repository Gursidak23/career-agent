"""Shared types for the email finder provider chain."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Verification grades, ordered weakest -> strongest.
GRADE_UNVERIFIED = "unverified"
GRADE_MX_ONLY = "mx_only"
GRADE_VERIFIED = "verified"

_GRADE_RANK = {GRADE_UNVERIFIED: 0, GRADE_MX_ONLY: 1, GRADE_VERIFIED: 2}


@dataclass
class EmailCandidate:
    email: str
    source: str  # crawler | pattern | apify | agentql
    confidence: float = 0.5  # 0..1
    verified: str = GRADE_UNVERIFIED  # one of the GRADE_* values
    name: str | None = None

    @property
    def grade_rank(self) -> int:
        return _GRADE_RANK.get(self.verified, 0)

    def sort_key(self) -> tuple[int, float]:
        # Higher verification grade first, then higher confidence.
        return (self.grade_rank, self.confidence)


class EmailFinder(Protocol):
    name: str

    async def find(
        self,
        *,
        name: str | None,
        company: str,
        domain: str | None,
        job_url: str | None,
    ) -> list[EmailCandidate]: ...
