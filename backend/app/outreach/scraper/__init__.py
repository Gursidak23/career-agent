"""Pluggable job sources — all real, live integrations (no sample data).

Default sources use free, keyless public APIs:
  - `all`        aggregate of the real sources below (recommended default)
  - `remotive`   https://remotive.com/api/remote-jobs
  - `remoteok`   https://remoteok.com/api
  - `arbeitnow`  https://www.arbeitnow.com/api/job-board-api
  - `hackernews` YC "Ask HN: Who is hiring?" monthly thread (often has emails)

`apify` aggregates Indian job boards (Naukri/Foundit/Hirist/Indeed/Internshala/
LinkedIn) via the Apify "New Job Posts Finder" actor — needs a free Apify token.
`scrapy` integrates an external Scrapy project from GitHub (see scrapy_source.py)
for boards that require a dedicated crawler (e.g. WellFound).
"""

from __future__ import annotations

from .aggregate import AggregateSource
from .apify_jobs import ApifyJobsSource
from .arbeitnow import ArbeitnowSource
from .base import JobRecord, JobSource
from .hackernews import HackerNewsSource
from .remoteok import RemoteOkSource
from .remotive import RemotiveSource
from .scrapy_source import ScrapySource

_SOURCES: dict[str, JobSource] = {
    "all": AggregateSource(),
    "remotive": RemotiveSource(),
    "remoteok": RemoteOkSource(),
    "arbeitnow": ArbeitnowSource(),
    "hackernews": HackerNewsSource(),
    "apify": ApifyJobsSource(),
    "scrapy": ScrapySource(),
}


def get_source(name: str) -> JobSource:
    if name not in _SOURCES:
        raise KeyError(f"Unknown job source '{name}'. Available: {', '.join(_SOURCES)}")
    return _SOURCES[name]


def source_names() -> list[str]:
    return list(_SOURCES)


__all__ = ["JobRecord", "JobSource", "get_source", "source_names"]
