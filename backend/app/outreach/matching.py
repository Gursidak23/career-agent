"""Score how well a resume fits a job post: fast, deterministic, no LLM.

Keywords come from the post itself (title + description) using the same skill
vocabulary as the ATS scorer. A keyword counts as matched when the resume
mentions it (synonyms and plurals included). Posts that name only a few skills
say little about fit, so the score is scaled down until a post names at least
five; a post naming none (often a non-tech role) scores 0.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..resume.ats import CANONICAL, extract_jd_keywords, mentions, resume_text
from ..resume.synonyms import variants_of
from ..schemas import ResumeData

_FULL_CONFIDENCE_AT = 5


@dataclass
class JobMatch:
    score: int  # 0-100
    matched: list[str]
    missing: list[str]


def job_keywords(title: str, description: str | None) -> list[str]:
    post = f"{title}\n{description or ''}"
    low = post.lower()
    # Very short terms ("go", "r") collide with ordinary words; count one only
    # when an unambiguous form of it appears ("golang").
    keys = [k for k in extract_jd_keywords(post) if len(k) > 2]
    for short in (k for k in CANONICAL if len(k) <= 2):
        if any(len(v) > 2 and mentions(v, low) for v in variants_of(short)):
            keys.append(short)
    return keys


def match_job(
    resume_lower: str, title: str, description: str | None, role_category: str | None = None
) -> JobMatch:
    keys = job_keywords(title, description)
    matched = [k for k in keys if mentions(k, resume_lower)]
    missing = [k for k in keys if k not in matched]
    coverage = len(matched) / len(keys) if keys else 0.0
    confidence = min(1.0, len(keys) / _FULL_CONFIDENCE_AT)
    return JobMatch(
        score=round(100 * coverage * confidence),
        matched=[CANONICAL.get(k, k) for k in matched],
        missing=[CANONICAL.get(k, k) for k in missing],
    )


def resume_lower(resume: ResumeData) -> str:
    return resume_text(resume).lower()
