"""Heuristic ATS scorer (0-100) over structured ResumeData.

The score is deterministic and explainable so the tailoring loop can optimize
against it. Components and weights:

- keyword coverage vs role/JD .......... 35
- standard sections present ............. 15
- quantified bullets + action verbs ..... 15
- parseability (contact/sections parse).. 15
- contact details + links ............... 10
- length / conciseness .................. 10
"""

from __future__ import annotations

import re

from ..schemas import AtsComponent, AtsReport, ResumeData
from .roles import ROLES, get_role
from .synonyms import variants_of

ACTION_VERBS = {
    "built", "designed", "developed", "implemented", "led", "created", "improved",
    "increased", "decreased", "reduced", "optimized", "launched", "shipped",
    "architected", "automated", "scaled", "migrated", "delivered", "managed",
    "engineered", "deployed", "integrated", "analyzed", "researched", "drove",
    "owned", "established", "accelerated", "streamlined", "refactored", "spearheaded",
    "boosted", "cut", "saved", "generated", "achieved", "mentored", "collaborated",
}

# Any digit counts as a metric (40%, $2M, 3x, 10k users). A bare "x\b" used to
# match words like "Linux"/"Redux" and wrongly mark bullets as quantified.
_NUMBER = re.compile(r"\d")
_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.]*")

_MASTER_SKILLS = sorted(
    {kw.lower() for profile in ROLES.values() for kw in profile.keywords},
    key=len,
    reverse=True,
)


# Display casing for role keywords ("postgresql" -> "PostgreSQL").
CANONICAL = {kw.lower(): kw for profile in ROLES.values() for kw in profile.keywords}


def mentions(term: str, text_lower: str) -> bool:
    """Whether lowercase text mentions the term (synonyms and simple plurals count)."""
    forms = set(variants_of(term))
    forms |= {f.removesuffix("s") for f in forms if len(f) > 3} | {f + "s" for f in forms}
    return any(_word_present(f, text_lower) for f in forms)


def unsupported_terms(new: str, old: str, evidence: str) -> list[str]:
    """Technical terms the rewrite introduces that the original never mentions.

    `new`/`old` are the rewritten and original line, `evidence` the whole original
    resume (all lowercase). Very short terms ("go", "r") are skipped: they collide
    with ordinary English words.
    """
    out = []
    for term in _MASTER_SKILLS:
        if len(term) <= 2:
            continue
        if mentions(term, new) and not mentions(term, old) and not mentions(term, evidence):
            out.append(term)
    return out


def resume_text(resume: ResumeData) -> str:
    return _resume_text(resume)


def _resume_text(resume: ResumeData) -> str:
    parts: list[str] = []
    if resume.summary:
        parts.append(resume.summary)
    parts.extend(resume.skills)
    for exp in resume.experience:
        parts.append(f"{exp.title} {exp.company}")
        parts.extend(exp.bullets)
    for proj in resume.projects:
        parts.append(proj.name)
        if proj.description:
            parts.append(proj.description)
        parts.extend(proj.tech)
        parts.extend(proj.bullets)
    for edu in resume.education:
        parts.append(f"{edu.degree} {edu.institution}")
    parts.extend(c.name for c in resume.certifications)
    for section in resume.extra_sections:
        parts.extend(section.items)
    if resume.contact.headline:
        parts.append(resume.contact.headline)
    return "\n".join(parts)


def _all_bullets(resume: ResumeData) -> list[str]:
    bullets: list[str] = []
    for exp in resume.experience:
        bullets.extend(exp.bullets)
    for proj in resume.projects:
        bullets.extend(proj.bullets)
    return [b for b in bullets if b.strip()]


def extract_jd_keywords(job_description: str) -> list[str]:
    """Pull known technical skills out of a job description."""
    jd = job_description.lower()
    # Word-boundary match: a plain substring test made "r" match every JD and
    # "go" match "good", padding the targets with skills the JD never asked for.
    found = [skill for skill in _MASTER_SKILLS if _word_present(skill, jd)]
    # Preserve a stable, de-duplicated order.
    seen: set[str] = set()
    out: list[str] = []
    for skill in found:
        if skill not in seen:
            seen.add(skill)
            out.append(skill)
    return out


def target_keywords(role: str, job_description: str | None) -> list[str]:
    profile = get_role(role)
    base = [k.lower() for k in profile.keywords]
    if job_description:
        jd_keys = extract_jd_keywords(job_description)
        # JD keywords first (most relevant), then role baseline.
        merged = jd_keys + [k for k in base if k not in set(jd_keys)]
        return merged
    return base


def _word_present(term: str, low: str) -> bool:
    # Word-boundary-ish match (handles "c++", "next.js" too).
    return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", low) is not None


_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.\-]*")


def _ngrams(low: str, max_n: int = 3) -> list[str]:
    tokens = _TOKEN.findall(low)
    grams: list[str] = []
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            grams.append(" ".join(tokens[i : i + n]))
    return grams


def _keyword_match(
    text: str, keywords: list[str], *, fuzzy_threshold: int = 90
) -> tuple[list[str], list[str]]:
    """Match keywords using synonyms/abbreviations and (optionally) fuzzy matching."""
    low = text.lower()

    # Try rapidfuzz for near-miss matching; degrade to exact/synonym-only if absent.
    fuzz = None
    grams: list[str] = []
    try:
        from rapidfuzz import fuzz as _fuzz

        fuzz = _fuzz
        grams = _ngrams(low)
    except Exception:  # noqa: BLE001 - rapidfuzz optional
        fuzz = None

    matched, missing = [], []
    for kw in keywords:
        variants = variants_of(kw)
        if any(_word_present(v, low) for v in variants):
            matched.append(kw)
            continue
        hit = False
        if fuzz is not None and grams:
            for v in variants:
                # Multi-word keywords need phrase-level comparison.
                best = max((fuzz.ratio(v, g) for g in grams), default=0)
                if best >= fuzzy_threshold:
                    hit = True
                    break
        (matched if hit else missing).append(kw)
    return matched, missing


def _stuffing_factor(text: str, matched: list[str]) -> float:
    """Return a 0..1 multiplier that penalizes obvious keyword stuffing.

    If matched keywords are repeated far more than needed (gaming the score),
    scale the keyword component down a little.
    """
    if not matched:
        return 1.0
    low = text.lower()
    total = 0
    for kw in matched:
        total += sum(low.count(v) for v in variants_of(kw))
    avg_repeats = total / len(matched)
    if avg_repeats <= 3:
        return 1.0
    if avg_repeats >= 8:
        return 0.85
    # Linear taper between 3 and 8 average repeats.
    return 1.0 - 0.15 * (avg_repeats - 3) / 5


def score_resume(resume: ResumeData, role: str, job_description: str | None = None) -> AtsReport:
    text = _resume_text(resume)
    keywords = target_keywords(role, job_description)
    matched, missing = _keyword_match(text, keywords)

    components: list[AtsComponent] = []
    suggestions: list[str] = []

    # 1) Keyword coverage (35), with an anti-stuffing guard.
    coverage = (len(matched) / len(keywords)) if keywords else 0.0
    stuffing = _stuffing_factor(text, matched)
    kw_score = round(35 * min(1.0, coverage / 0.6) * stuffing, 2)  # 60% coverage = full marks
    stuffing_note = "" if stuffing >= 0.999 else " (keyword-stuffing penalty applied)"
    components.append(
        AtsComponent(
            name="Keyword coverage",
            score=kw_score,
            max=35,
            detail=f"{len(matched)}/{len(keywords)} target keywords present.{stuffing_note}",
        )
    )
    if missing:
        suggestions.append(
            "Add or surface these relevant keywords where truthful: "
            + ", ".join(missing[:12])
        )

    # 2) Standard sections (15)
    section_flags = {
        "contact": bool(resume.contact.name and (resume.contact.email or resume.contact.phone)),
        "skills": len(resume.skills) >= 3,
        "experience_or_projects": bool(resume.experience or resume.projects),
        "education": bool(resume.education),
    }
    sec_score = round(15 * (sum(section_flags.values()) / len(section_flags)), 2)
    missing_sections = [name for name, ok in section_flags.items() if not ok]
    components.append(
        AtsComponent(
            name="Standard sections",
            score=sec_score,
            max=15,
            detail="Present: " + ", ".join(n for n, ok in section_flags.items() if ok),
        )
    )
    if missing_sections:
        suggestions.append("Add/complete sections: " + ", ".join(missing_sections))

    # 3) Quantified bullets + action verbs (15)
    bullets = _all_bullets(resume)
    if bullets:
        strong = 0
        for b in bullets:
            first = (_WORD.search(b).group(0).lower() if _WORD.search(b) else "")
            has_verb = first in ACTION_VERBS
            has_number = bool(_NUMBER.search(b))
            if has_verb and has_number:
                strong += 1
            elif has_verb or has_number:
                strong += 0.5
        quality = strong / len(bullets)
        q_score = round(15 * min(1.0, quality / 0.7), 2)
        detail = f"{len(bullets)} bullets; strong action+metric ratio {quality:.0%}."
    else:
        q_score = 0.0
        detail = "No experience/project bullets found."
    components.append(
        AtsComponent(name="Quantified achievements", score=q_score, max=15, detail=detail)
    )
    if q_score < 12:
        suggestions.append(
            "Rewrite bullets as 'Action verb + what you did + quantified result' "
            "(e.g. 'Reduced API latency by 40% by adding Redis caching')."
        )

    # 4) Parseability (15) - structured single-column data with parseable contact.
    parse_ok = 0
    if resume.contact.email:
        parse_ok += 1
    if resume.contact.name:
        parse_ok += 1
    if resume.skills:
        parse_ok += 1
    if bullets:
        parse_ok += 1
    p_score = round(15 * (parse_ok / 4), 2)
    components.append(
        AtsComponent(
            name="Parseability",
            score=p_score,
            max=15,
            detail="Single-column, machine-readable fields (clean LaTeX output).",
        )
    )

    # 5) Contact + links (10)
    contact_points = sum(
        bool(x)
        for x in (
            resume.contact.email,
            resume.contact.phone,
            resume.contact.linkedin,
            resume.contact.github or resume.contact.website,
        )
    )
    c_score = round(10 * (contact_points / 4), 2)
    components.append(
        AtsComponent(
            name="Contact & links",
            score=c_score,
            max=10,
            detail=f"{contact_points}/4 of email, phone, LinkedIn, GitHub/site present.",
        )
    )
    if contact_points < 4:
        suggestions.append("Add missing contact details: email, phone, LinkedIn, GitHub/portfolio.")

    # 6) Length / conciseness (10)
    n_bullets = len(bullets)
    if 8 <= n_bullets <= 28:
        l_score = 10.0
    elif n_bullets < 8:
        l_score = round(10 * (n_bullets / 8), 2)
    else:
        l_score = round(max(5.0, 10 - (n_bullets - 28) * 0.3), 2)
    components.append(
        AtsComponent(
            name="Length & conciseness",
            score=l_score,
            max=10,
            detail=f"{n_bullets} total bullets.",
        )
    )

    total = round(sum(c.score for c in components), 2)
    return AtsReport(
        score=total,
        components=components,
        matched_keywords=matched,
        missing_keywords=missing,
        suggestions=suggestions,
    )
