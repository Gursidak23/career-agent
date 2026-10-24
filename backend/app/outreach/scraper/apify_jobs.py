"""Apify-backed Indian job boards (real; needs a free Apify token).

Runs the "New Job Posts Finder" actor (spartany/new-job-posts-finder), which
aggregates fresher/entry-level tech roles across Naukri, Indeed, LinkedIn,
Internshala, Foundit (Monster India), and Hirist, then returns a de-duplicated
list. Dormant until an Apify token is configured:

    CAREER_SCRAPER__APIFY_TOKEN=...        (or reuses CAREER_EMAILFINDER__APIFY_TOKEN)
"""

from __future__ import annotations

from ...config import get_settings
from .base import JobRecord
from .classify import infer_experience, infer_role_category, normalize_job_type
from .http import post_json

RUN_SYNC_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


def _resolve_token() -> str | None:
    s = get_settings()
    # Prefer the scraper-specific token; fall back to the email-finder one.
    return s.scraper.apify_token or s.emailfinder.apify_token


class ApifyJobsSource:
    name = "apify"

    def fetch(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        limit: int = 25,
    ) -> list[JobRecord]:
        settings = get_settings().scraper
        token = _resolve_token()
        if not token:
            raise RuntimeError(
                "Apify job source not configured. Set CAREER_SCRAPER__APIFY_TOKEN "
                "(a free Apify token) to enable Indian job boards "
                "(Naukri/Foundit/Hirist/Indeed/Internshala/LinkedIn)."
            )

        actor = settings.apify_jobs_actor.replace("/", "~")
        url = RUN_SYNC_URL.format(actor=actor)
        body: dict[str, object] = {
            "scraperMode": settings.apify_mode,
            "location": location or settings.apify_location,
            "maxJobsPerZone": 0,
        }
        if query:
            body["keywords"] = query

        items = post_json(
            url,
            json_body=body,
            params={"token": token},
            timeout=settings.apify_timeout_seconds,
        )
        if not isinstance(items, list):
            return []

        records: list[JobRecord] = []
        for j in items:
            if not isinstance(j, dict):
                continue
            title = j.get("title", "") or ""
            company = j.get("company", "") or ""
            if not company and not title:
                continue
            description = (j.get("keyword") or "").strip()
            board = j.get("source") or "apify"
            records.append(
                JobRecord(
                    source="apify",
                    external_id=j.get("link"),
                    title=title,
                    company=company,
                    location=j.get("location") or location or "India",
                    job_type=normalize_job_type(None, title=title),
                    # The actor only returns 0-1 yr (fresher) roles.
                    experience=infer_experience(title) if "senior" in title.lower() else "entry",
                    role_category=infer_role_category(title, None, description),
                    description=description or None,
                    url=j.get("link"),
                    extra={"board": board, "date_posted": j.get("datePosted")},
                )
            )
            if len(records) >= limit:
                break
        return records
