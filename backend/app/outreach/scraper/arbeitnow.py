"""Arbeitnow job board (real, keyless public API).

https://www.arbeitnow.com/api/job-board-api
"""

from __future__ import annotations

from .base import JobRecord
from .classify import clean_html, infer_experience, infer_role_category, normalize_job_type
from .http import get_json

API_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowSource:
    name = "arbeitnow"

    def fetch(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        limit: int = 25,
    ) -> list[JobRecord]:
        data = get_json(API_URL)
        jobs = data.get("data", []) if isinstance(data, dict) else []

        q = (query or "").lower()
        loc = (location or "").lower()
        records: list[JobRecord] = []
        for j in jobs:
            title = j.get("title", "") or ""
            tags = j.get("tags", []) or []
            job_types = j.get("job_types", []) or []
            description = clean_html(j.get("description"))
            location_str = j.get("location") or ("Remote" if j.get("remote") else "")

            blob = f"{title} {' '.join(tags)} {description}".lower()
            if q and q not in blob:
                continue
            if loc and loc not in location_str.lower():
                continue

            raw_type = job_types[0] if job_types else None
            records.append(
                JobRecord(
                    source="arbeitnow",
                    external_id=str(j.get("slug")) if j.get("slug") else None,
                    title=title,
                    company=j.get("company_name", "") or "",
                    location=location_str or "Remote",
                    job_type=normalize_job_type(raw_type, title=title, description=description),
                    experience=infer_experience(title, description),
                    role_category=infer_role_category(title, tags, description),
                    description=description,
                    url=j.get("url"),
                    extra={"tags": tags, "remote": j.get("remote")},
                )
            )
            if len(records) >= limit:
                break
        return records
