"""Remotive job board (real, keyless public API).

https://remotive.com/api/remote-jobs
"""

from __future__ import annotations

from .base import JobRecord
from .classify import clean_html, infer_experience, infer_role_category, normalize_job_type
from .http import get_json

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource:
    name = "remotive"

    def fetch(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        limit: int = 25,
    ) -> list[JobRecord]:
        params: dict[str, object] = {"limit": max(1, min(limit, 100))}
        if query:
            params["search"] = query
        data = get_json(API_URL, params=params)
        jobs = data.get("jobs", []) if isinstance(data, dict) else []

        records: list[JobRecord] = []
        for j in jobs:
            title = j.get("title", "") or ""
            tags = j.get("tags", []) or []
            description = clean_html(j.get("description"))
            loc = j.get("candidate_required_location") or "Remote"
            if location and location.lower() not in loc.lower():
                continue
            records.append(
                JobRecord(
                    source="remotive",
                    external_id=str(j.get("id")) if j.get("id") is not None else None,
                    title=title,
                    company=j.get("company_name", "") or "",
                    location=loc,
                    job_type=normalize_job_type(j.get("job_type"), title=title, description=description),
                    experience=infer_experience(title, description),
                    role_category=infer_role_category(title, tags, description),
                    description=description,
                    url=j.get("url"),
                    extra={"tags": tags, "salary": j.get("salary"), "category": j.get("category")},
                )
            )
            if len(records) >= limit:
                break
        return records
