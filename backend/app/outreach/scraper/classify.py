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


_TECH_TITLE = re.compile(
    r"engineer|developer|scientist|programmer|architect|devops|\bswe\b|\bsre\b|"
    r"data analyst",
    re.IGNORECASE,
)
_NON_TECH_TITLE = re.compile(
    r"\b(sales|account|solutions?|support|customer|field|recruit\w*|marketing|legal|"
    r"finance|partner|talent|business development)\b",
    re.IGNORECASE,
)


def is_tech_role(title: str) -> bool:
    """Engineering/data/ML roles; excludes sales-, support- and solutions-type titles."""
    return bool(_TECH_TITLE.search(title)) and not _NON_TECH_TITLE.search(title)


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


def _has_word(keyword: str, text: str) -> bool:
    # Whole-word match: "intern" must not match "internal", nor "lead" "leading".
    return re.search(r"(?<![a-z])" + re.escape(keyword.strip()) + r"(?![a-z])", text) is not None


_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs)", re.IGNORECASE)


def infer_experience(title: str, description: str = "") -> str:
    """Seniority from the title; else from an explicit "N+ years" requirement.

    Descriptions are not keyword-scanned: words like "lead" or "senior" appear
    there as verbs and team descriptions ("you'll lead...", "senior leadership").
    """
    text = _norm(title)
    for level, keywords in _EXPERIENCE_KEYWORDS:
        if any(_has_word(k, text) for k in keywords):
            return level
    years = [int(y) for y in _YEARS.findall(description or "") if int(y) <= 20]
    if years:
        y = min(years)
        return "junior" if y <= 1 else "mid" if y <= 4 else "senior" if y <= 7 else "lead"
    return "mid"


def normalize_job_type(raw: str | None, *, title: str = "", description: str = "") -> str:
    """From the source's own field, then the title, then (cautiously) the description."""
    if raw:
        # "FullTime" (Ashby) -> "full time"
        r = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw).lower().replace("_", " ").replace("-", " ")
        for canonical, keywords in _JOB_TYPE_KEYWORDS:
            if any(_has_word(k, r) for k in keywords):
                return canonical
    for canonical, keywords in _JOB_TYPE_KEYWORDS:
        if any(_has_word(k, _norm(title)) for k in keywords):
            return canonical
    # Descriptions mention interns and contractors in passing ("mentor interns",
    # "work with contractors"), so only the explicit employment-type phrases count.
    desc = (description or "").lower()
    for canonical, phrase in (("part_time", "part-time"), ("part_time", "part time"), ("contract", "contract role"),
                              ("contract", "contract position"), ("freelance", "freelance")):
        if phrase in desc:
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
    "is_tech_role",
]
