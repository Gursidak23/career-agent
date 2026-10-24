"""RemoteOK job board (real, keyless public API).

https://remoteok.com/api  (first array element is a legal/metadata notice)
"""

from __future__ import annotations

from .base import JobRecord
from .classify import clean_html, infer_experience, infer_role_category, normalize_job_type
from .http import get_json

API_URL = "https://remoteok.com/api"


class RemoteOkSource:
    name = "remoteok"

    def fetch(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        limit: int = 25,
    ) -> list[JobRecord]:
        data = get_json(API_URL)
        if not isinstance(data, list):
            return []

        q = (query or "").lower()
        loc = (location or "").lower()
        records: list[JobRecord] = []
        for j in data:
            # Skip the leading metadata object (has no "position"/"id" job fields).
            if not isinstance(j, dict) or not j.get("id") or not j.get("position"):
                continue
            title = j.get("position", "") or ""
            tags = j.get("tags", []) or []
            description = clean_html(j.get("description"))
            location_str = j.get("location") or "Remote"

            blob = f"{title} {' '.join(tags)} {description}".lower()
            if q and q not in blob:
                continue
            if loc and loc not in location_str.lower():
                continue

            records.append(
                JobRecord(
                    source="remoteok",
                    external_id=str(j.get("id")),
                    title=title,
                    company=j.get("company", "") or "",
                    location=location_str,
                    job_type=normalize_job_type(None, title=title, description=description),
                    experience=infer_experience(title, description),
                    role_category=infer_role_category(title, tags, description),
                    description=description,
                    url=j.get("url") or j.get("apply_url"),
                    extra={
                        "tags": tags,
                        "salary_min": j.get("salary_min"),
                        "salary_max": j.get("salary_max"),
                    },
                )
            )
            if len(records) >= limit:
                break
        return records
