"""Infer structured fields (role category, experience, job type) from the free
text returned by real job boards.

Real APIs rarely return our normalized categories, so we derive them from the
title, tags, and description using keyword heuristics.
"""

from __future__ import annotations

import html
import re

from ..filters import EXPERIENCE_LEVELS, JOB_TYPES

# role_category -> title/tag keywords (checked against title + tags first).
_ROLE_TITLE_KEYWORDS: dict[str, list[str]] = {
    "ai_engineer": [
        "ai engineer", "ml engineer", "machine learning", "deep learning", "nlp",
        "llm", "computer vision", "ai/ml", "artificial intelligence",
    ],
    "data_scientist": ["data scientist", "data science", "research scientist"],
    "data_engineer": ["data engineer", "analytics engineer", "etl", "data platform"],
    "devops_engineer": [
        "devops", "sre", "site reliability", "platform engineer", "infrastructure",
        "cloud engineer", "systems engineer",
    ],
    "app_developer": [
        "android", "ios", "mobile", "flutter", "react native", "swift", "kotlin",
    ],
    "web_developer": [
        "frontend", "front-end", "front end", "web developer", "ui engineer",
        "react developer", "full stack", "full-stack", "fullstack",
    ],
    "backend_engineer": ["backend", "back-end", "back end", "server-side", "api engineer"],
    "software_developer": [
        "software engineer", "software developer", "programmer", "swe", "developer",
    ],
}

_EXPERIENCE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("lead", ["lead", "principal", "staff", "head of", "vp ", "director"]),
    ("senior", ["senior", "sr.", "sr ", " iii", "expert"]),
    ("entry", ["intern", "internship", "trainee", "apprentice"]),
    ("junior", ["junior", "jr.", "jr ", "entry level", "entry-level", "graduate", "new grad"]),
    # "mid" is the default when nothing else matches.
]

_JOB_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("internship", ["intern", "internship"]),
    ("part_time", ["part time", "part-time", "parttime"]),
    ("contract", ["contract", "contractor", "b2b"]),
    ("freelance", ["freelance", "freelancer"]),
    ("full_time", ["full time", "full-time", "fulltime", "permanent"]),
]


def _norm(*parts: object) -> str:
    return " ".join(str(p) for p in parts if p).lower()


def infer_role_category(title: str, tags: list[str] | None = None, description: str = "") -> str:
    haystack_title = _norm(title, " ".join(tags or []))
    # Title/tags are the strongest signal; check specific roles before the generic
    # "software_developer" fallback by iterating in declared order.
    for category, keywords in _ROLE_TITLE_KEYWORDS.items():
        if category == "software_developer":
            continue
        if any(k in haystack_title for k in keywords):
            return category
    # Generic developer titles.
    if any(k in haystack_title for k in _ROLE_TITLE_KEYWORDS["software_developer"]):
        return "software_developer"
    # Last resort: scan description for the most distinctive role keywords.
    desc = description.lower()
    for category, keywords in _ROLE_TITLE_KEYWORDS.items():
        if category == "software_developer":
            continue
        if any(k in desc for k in keywords):
            return category
    return "software_developer"


def infer_experience(title: str, description: str = "") -> str:
    text = _norm(title)
    for level, keywords in _EXPERIENCE_KEYWORDS:
        if any(k in text for k in keywords):
            return level
    # Fall back to scanning the description for explicit seniority cues.
    dtext = description.lower()
    for level, keywords in _EXPERIENCE_KEYWORDS:
        if any(k in dtext for k in keywords):
            return level
    return "mid"


def normalize_job_type(raw: str | None, *, title: str = "", description: str = "") -> str:
    if raw:
        r = raw.lower().replace("_", " ").replace("-", " ")
        for canonical, keywords in _JOB_TYPE_KEYWORDS:
            if any(k in r for k in keywords):
                return canonical
    text = _norm(title, description)
    for canonical, keywords in _JOB_TYPE_KEYWORDS:
        if any(k in text for k in keywords):
            return canonical
    return "full_time"


def clean_html(text: str | None, *, limit: int = 1200) -> str:
    """Strip HTML tags/entities from a description for clean storage/display."""
    if not text:
        return ""
    # Keep paragraph/line breaks so long descriptions stay readable in the UI.
    with_breaks = re.sub(r"(?i)<\s*(?:br|/?p|/li|/div|/h[1-6])\b[^>]*>", "\n", text)
    no_tags = re.sub(r"<[^>]+>", " ", with_breaks)
    # html.unescape handles every entity (e.g. "&#x2F;" in HN posts), not a fixed few.
    unescaped = html.unescape(no_tags).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in unescaped.split("\n")]
    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return collapsed[:limit]


__all__ = [
    "EXPERIENCE_LEVELS",
    "JOB_TYPES",
    "infer_role_category",
    "infer_experience",
    "normalize_job_type",
    "clean_html",
]
