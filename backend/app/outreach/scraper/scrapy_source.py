"""Adapter that integrates an external Scrapy project (cloned from GitHub).

This does NOT bundle a scraper for any specific job board (those break often and
have ToS/anti-bot constraints). Instead it shells out to an existing Scrapy
project you point it at, then maps the spider's JSON Lines output into JobRecords.

Setup (one time):
    git clone <a maintained Scrapy job-board project> external/job-scraper
    cd external/job-scraper && pip install -r requirements.txt

Then configure environment variables:
    CAREER_SCRAPER__PROJECT_DIR=external/job-scraper
    CAREER_SCRAPER__SPIDER=wellfound        # the spider name in that project

The spider is expected to yield items with (some of) these fields:
    title, company, location, job_type, experience, role_category,
    description, url, recruiter_name, recruiter_email, id

Field names are flexible: see FIELD_ALIASES below for the mapping applied.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from ...logging_setup import get_logger
from .base import JobRecord

log = get_logger(__name__)

FIELD_ALIASES = {
    "title": ["title", "job_title", "position", "name"],
    "company": ["company", "company_name", "organization", "org"],
    "location": ["location", "city", "place"],
    "job_type": ["job_type", "employment_type", "type"],
    "experience": ["experience", "experience_level", "seniority"],
    "role_category": ["role_category", "category", "function"],
    "description": ["description", "desc", "summary", "details"],
    "url": ["url", "link", "apply_url", "job_url"],
    "recruiter_name": ["recruiter_name", "contact_name", "poster"],
    "recruiter_email": ["recruiter_email", "contact_email", "email"],
    "external_id": ["id", "external_id", "job_id", "uid"],
}


def _pick(item: dict, names: list[str]) -> str | None:
    for n in names:
        if item.get(n):
            return str(item[n])
    return None


def _to_record(item: dict) -> JobRecord:
    return JobRecord(
        source="scrapy",
        title=_pick(item, FIELD_ALIASES["title"]) or "",
        company=_pick(item, FIELD_ALIASES["company"]) or "",
        location=_pick(item, FIELD_ALIASES["location"]),
        job_type=_pick(item, FIELD_ALIASES["job_type"]),
        experience=_pick(item, FIELD_ALIASES["experience"]),
        role_category=_pick(item, FIELD_ALIASES["role_category"]),
        description=_pick(item, FIELD_ALIASES["description"]),
        url=_pick(item, FIELD_ALIASES["url"]),
        recruiter_name=_pick(item, FIELD_ALIASES["recruiter_name"]),
        recruiter_email=_pick(item, FIELD_ALIASES["recruiter_email"]),
        external_id=_pick(item, FIELD_ALIASES["external_id"]),
        extra=item,
    )


class ScrapySource:
    name = "scrapy"

    def __init__(self) -> None:
        # Read lazily so the package imports fine without scrapy installed.
        self.project_dir = os.getenv("CAREER_SCRAPER__PROJECT_DIR", "")
        self.spider = os.getenv("CAREER_SCRAPER__SPIDER", "")

    def _check_ready(self) -> Path:
        if not self.project_dir or not self.spider:
            raise RuntimeError(
                "Scrapy source not configured. Set CAREER_SCRAPER__PROJECT_DIR and "
                "CAREER_SCRAPER__SPIDER to an external Scrapy project (see scrapy_source.py)."
            )
        proj = Path(self.project_dir)
        if not proj.exists():
            raise RuntimeError(f"Scrapy project dir not found: {proj}")
        return proj

    def fetch(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        limit: int = 25,
    ) -> list[JobRecord]:
        proj = self._check_ready()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "jobs.jsonl"
            cmd = [
                "scrapy", "crawl", self.spider,
                "-O", str(out),
                "-s", f"CLOSESPIDER_ITEMCOUNT={limit}",
            ]
            # Pass query/location to the spider as -a args if it supports them.
            if query:
                cmd += ["-a", f"query={query}"]
            if location:
                cmd += ["-a", f"location={location}"]
            try:
                proc = subprocess.run(
                    cmd, cwd=str(proj), capture_output=True, text=True, timeout=300
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(f"Failed to run scrapy: {exc}") from exc
            if proc.returncode != 0 and not out.exists():
                raise RuntimeError(f"Scrapy crawl failed: {proc.stderr[-800:]}")

            records: list[JobRecord] = []
            if out.exists():
                for line in out.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(_to_record(json.loads(line)))
                    except json.JSONDecodeError:
                        continue
            log.info("scrapy source produced %d records", len(records))
            return records[:limit]
