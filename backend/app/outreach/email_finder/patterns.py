"""Pattern-based email guessing (free, no API key).

Given a person's name and a domain, generate the common corporate address
formats. Confidence reflects how common each pattern is; the service verifies
candidates and upgrades their grade afterwards.
"""

from __future__ import annotations

import re

from .base import EmailCandidate
from .domain import candidate_domains

_NAME_CLEAN = re.compile(r"[^a-z]+")

# pattern template -> base confidence (common formats score higher)
_PATTERNS: list[tuple[str, float]] = [
    ("{first}.{last}", 0.55),
    ("{first}{last}", 0.45),
    ("{f}{last}", 0.45),
    ("{first}", 0.30),
    ("{f}.{last}", 0.35),
    ("{first}_{last}", 0.25),
    ("{last}{f}", 0.20),
    ("{last}.{first}", 0.20),
]


def _split_name(name: str) -> tuple[str, str]:
    parts = [_NAME_CLEAN.sub("", p.lower()) for p in name.split()]
    parts = [p for p in parts if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def generate_emails(name: str, domain: str) -> list[tuple[str, float]]:
    first, last = _split_name(name)
    if not first:
        return []
    ctx = {"first": first, "last": last, "f": first[0] if first else ""}
    out: list[tuple[str, float]] = []
    seen: set[str] = set()
    for template, conf in _PATTERNS:
        # Skip last-name templates when we only have a single name.
        if not last and "{last}" in template:
            continue
        local = template.format(**ctx).strip("._")
        if not local or local in seen:
            continue
        seen.add(local)
        out.append((f"{local}@{domain}", conf))
    return out


class PatternFinder:
    name = "pattern"

    async def find(
        self,
        *,
        name: str | None,
        company: str,
        domain: str | None,
        job_url: str | None,
    ) -> list[EmailCandidate]:
        if not name:
            return []  # pattern guessing needs a person's name
        domains = [domain] if domain else candidate_domains(company)
        guessed_domain = domain is None
        candidates: list[EmailCandidate] = []
        for dom in domains:
            for email, conf in generate_emails(name, dom):
                # Guessed (name-derived) domains are riskier: discount confidence.
                candidates.append(
                    EmailCandidate(
                        email=email.lower(),
                        source="pattern",
                        confidence=conf * (0.6 if guessed_domain else 1.0),
                        name=name,
                    )
                )
        return candidates
