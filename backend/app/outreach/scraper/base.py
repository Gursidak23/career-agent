"""Job source interface shared by all providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class JobRecord:
    source: str
    title: str
    company: str
    location: str | None = None
    job_type: str | None = None
    experience: str | None = None
    role_category: str | None = None
    description: str | None = None
    url: str | None = None
    recruiter_name: str | None = None
    recruiter_email: str | None = None
    external_id: str | None = None
    extra: dict = field(default_factory=dict)


class JobSource(Protocol):
    name: str

    def fetch(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        limit: int = 25,
    ) -> list[JobRecord]: ...
