"""Resolve a company's email domain from available signals."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Domains that are never a company's mail domain.
_PUBLIC_HOSTS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
    "proton.me", "protonmail.com", "aol.com", "live.com",
}
# Job-board / aggregator hosts we should not treat as the employer domain.
_BOARD_HOSTS = {
    "linkedin.com", "indeed.com", "wellfound.com", "angel.co", "ycombinator.com",
    "instahyre.com", "naukri.com", "glassdoor.com", "lever.co", "greenhouse.io",
    "workable.com", "jobs.ashbyhq.com", "ashbyhq.com",
}

_SLUG = re.compile(r"[^a-z0-9]+")


def _registrable(host: str) -> str:
    host = host.lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url if "//" in url else f"//{url}")
    host = _registrable(parsed.netloc or parsed.path)
    if not host or "." not in host:
        return None
    base = ".".join(host.split(".")[-2:])
    if base in _BOARD_HOSTS or base in _PUBLIC_HOSTS:
        return None
    return host


def slug_from_company(company: str) -> str:
    return _SLUG.sub("", company.strip().lower())


def candidate_domains(company: str) -> list[str]:
    """Heuristic company-name -> likely domains (best-effort guesses)."""
    slug = slug_from_company(company)
    if not slug:
        return []
    return [f"{slug}.com", f"{slug}.io", f"{slug}.ai", f"{slug}.co"]


def resolve_domain(company: str, domain: str | None, job_url: str | None) -> str | None:
    """Pick the best-known domain: explicit > from job URL > None.

    Guessed name-based domains are intentionally NOT returned here; callers that
    want to guess use ``candidate_domains`` so guesses stay clearly separate from
    known domains.
    """
    if domain:
        return _registrable(domain)
    from_url = domain_from_url(job_url)
    if from_url:
        return from_url
    return None
