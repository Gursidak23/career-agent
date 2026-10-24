"""Role-aware resume tailoring loop that optimizes against the ATS scorer.

Each iteration asks the LLM to rewrite the resume (truthfully) to better match
the target role/JD and ATS best practices, then re-scores. We keep the highest
scoring version and stop once the target score is reached or iterations run out.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from ..config import get_settings
from ..llm import LlmError
from ..llm.router import complete_json
from ..logging_setup import get_logger
from ..schemas import AtsReport, BulletReview, ResumeData
from .ats import CANONICAL, mentions, resume_text, score_resume, target_keywords, unsupported_terms
from .parser import SCHEMA_HINT
from .roles import get_role

log = get_logger(__name__)

# Principles distilled from standard tech-resume guidance (single-column,
# standard sections, action+metric bullets, keyword alignment, no fabrication).
_TAILOR_SYSTEM = (
    "You are an expert technical resume writer and ATS optimization specialist. "
    "You rewrite resumes to maximize ATS score for a target role WITHOUT inventing "
    "any facts. Rules: keep all employers, titles, and dates truthful; only rephrase, "
    "reorganize, and surface existing skills; write bullets as 'strong action verb + "
    "what you did + quantified result'; reuse numbers already present and do not "
    "fabricate metrics; include a Skills section listing genuinely relevant keywords; "
    "use each keyword where it naturally fits, at most 2-3 times overall (repetition "
    "is penalized as keyword stuffing); only put a keyword in a bullet that already "
    "describes that kind of work, never graft unrelated terms onto a bullet; keep every "
    "experience, project, and education "
    "entry; use standard section names; keep it concise and single-column. "
    "Return ONLY a JSON object in the exact ResumeData schema given."
)

# Keep the output in the same shape as the input resume.
_FORMAT_RULES = """
Preserve the resume's format exactly:
- Same entries and the SAME NUMBER OF BULLETS per experience/project entry: rewrite
  each bullet in place; never add, drop, or merge bullets.
- Keep each bullet about as long as the original so the resume stays at {pages} page(s).
- Keep skill_groups with the same categories in the same order; within a group you may
  reorder skills and add ones the experience clearly demonstrates.
- Keep contact, education, certifications, extra_sections, and section_order unchanged.
- Only add a summary or project description if the original has one.
""".strip()


@dataclass
class TailorResult:
    resume: ResumeData
    report: AtsReport
    iterations: int
    # Set when the LLM produced nothing usable, i.e. the resume was not rewritten.
    warning: str | None = None
    # Line-by-line suggestions of the best candidate (applied or held back).
    reviews: list[BulletReview] = field(default_factory=list)


def _build_user_prompt(
    resume: ResumeData,
    role_label: str,
    emphasis: str,
    job_description: str | None,
    report: AtsReport,
    keywords: list[str],
) -> str:
    jd_block = f"\nTARGET JOB DESCRIPTION:\n\"\"\"\n{job_description}\n\"\"\"\n" if job_description else ""
    return f"""
Rewrite the following resume to target the role: {role_label}.
Focus: {emphasis}
{jd_block}
Keywords this resume already supports. Make them prominent where they describe
the real work (keep this exact capitalization):
{", ".join(CANONICAL.get(k, k) for k in report.matched_keywords[:30]) or "none"}

Keywords the role wants that this resume does NOT support. Do NOT add these
anywhere; the candidate has not done this work:
{", ".join(CANONICAL.get(k, k) for k in report.missing_keywords[:30]) or "none"}

Current ATS score: {report.score}/100. Improve it honestly: stronger action verbs,
clearer impact using the numbers already present, and better emphasis of the
supported keywords above.

{_FORMAT_RULES.format(pages=resume.layout.pages or 1)}

{SCHEMA_HINT}

CURRENT RESUME JSON:
{resume.model_dump_json()}
""".strip()


# Real words that are also technology names; never force-capitalize these.
_AMBIGUOUS = {"express", "spark", "swift", "react", "dart", "rust", "flask"}


def _is_name(term: str) -> bool:
    """A product/tech name (PostgreSQL, LangGraph, ONNX, C++), not a title-cased word.

    Skill lists capitalize ordinary words ("Reranking", "Hybrid Search"); forcing
    that casing into prose ("..., Reranking the top 6") would be wrong.
    """
    return any(
        any(c.isupper() for c in w[1:]) or not w.isalpha() or (len(w) > 1 and w.isupper())
        for w in term.split()
    )


def _casing_map(original: ResumeData) -> dict[str, str]:
    """lowercase -> preferred casing; the candidate's own spelling of names wins."""
    canon = dict(CANONICAL)
    canon.update({s.lower(): s for s in original.skills if _is_name(s)})
    return {k: v for k, v in canon.items() if len(k) > 2 and k != v and k not in _AMBIGUOUS}


def _recase(text: str, casing: dict[str, str]) -> str:
    """Restore 'python' -> 'Python' etc. where the model lowercased a technology."""
    if not text or not casing:
        return text
    pattern = re.compile(
        r"(?<![A-Za-z0-9])(" + "|".join(re.escape(k) for k in sorted(casing, key=len, reverse=True)) + r")(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    return pattern.sub(lambda m: casing[m.group(0).lower()] if m.group(0).islower() else m.group(0), text)


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# Product/tech names: inner capitals (OrderBot, LangGraph) or acronyms (HMAC, MCP).
_NAME = re.compile(r"\b(?:[A-Za-z]*[a-z][A-Z]\w*|[A-Z]{2,}[A-Za-z0-9]*)\b")


def _lost_facts(new: str, old: str) -> list[str]:
    """Numbers and distinctive names of the original line that the rewrite dropped."""
    new_numbers = set(_NUMBER.findall(new))
    new_names = {n.lower() for n in _NAME.findall(new)}
    lost = [n for n in dict.fromkeys(_NUMBER.findall(old)) if n not in new_numbers]
    lost += [n for n in dict.fromkeys(_NAME.findall(old)) if n.lower() not in new_names]
    return lost


def _key(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def lock_facts(original: ResumeData, candidate: ResumeData) -> tuple[ResumeData, list[BulletReview]]:
    """Keep everything that must not change from the original; take only clean rewrites.

    The LLM may reword bullets, the summary, the headline and skills, but employers,
    titles, dates, contact details, education, certifications, links, extra sections
    and the section order always come from the original, whatever the model returns.
    Skills (and project tech) the model adds survive only if the original already
    mentions them, and technology names keep their proper casing.

    Every reworded line is returned as a BulletReview. Clean ones are applied; ones
    that add technologies the original never mentions, or drop a number or name,
    are held back with the reason, for the user to accept or reject.
    """
    casing = _casing_map(original)
    evidence = resume_text(original).lower()
    known = {s.lower() for s in original.skills}
    reviews: list[BulletReview] = []

    def truthful(skills: list[str]) -> list[str]:
        seen: set[str] = set()
        out = []
        for s in skills:
            s = _recase(s.strip(), casing)
            if s and s.lower() not in seen and (s.lower() in known or mentions(s, evidence)):
                seen.add(s.lower())
                out.append(s)
        return out

    def review(section: str, entry: int, index: int, label: str, new: str | None, old: str | None, scope: str) -> str | None:
        """Record a reworded line; return the text to use (the rewrite only if clean)."""
        if not new or not old:
            return old
        new = _recase(new.strip(), casing)
        if new == old:
            return old
        flags = []
        terms = unsupported_terms(new.lower(), old.lower(), scope)
        if terms:
            flags.append("Adds " + ", ".join(CANONICAL.get(t, t) for t in terms) + ", not in your original")
        lost = _lost_facts(new, old)
        if lost:
            flags.append("Drops " + ", ".join(lost))
        reviews.append(
            BulletReview(
                section=section, entry=entry, index=index, label=label,
                original=old, suggested=new, flags=flags, applied=not flags,
            )
        )
        return old if flags else new

    def bullets(section: str, entry: int, label: str, new: list[str], old: list[str], scope: str) -> list[str]:
        """Bullets may only mention technologies their own entry already mentions.

        A changed bullet count breaks the original layout, so it is ignored.
        """
        if len(new) != len(old):
            return old
        return [review(section, entry, j, label, n, o, scope) or o for j, (n, o) in enumerate(zip(new, old, strict=True))]

    exp_by_company = {_key(e.company): e for e in candidate.experience}
    experience = []
    for i, orig in enumerate(original.experience):
        new = exp_by_company.get(_key(orig.company))
        if new is None and len(candidate.experience) == len(original.experience):
            new = candidate.experience[i]
        scope = " ".join([orig.title, orig.company, *orig.bullets]).lower()
        experience.append(
            orig.model_copy(
                update={"bullets": bullets("experience", i, orig.company, new.bullets if new else [], orig.bullets, scope)}
            )
        )

    proj_by_name = {_key(p.name): p for p in candidate.projects}
    projects = []
    for i, orig in enumerate(original.projects):
        new = proj_by_name.get(_key(orig.name))
        if new is None and len(candidate.projects) == len(original.projects):
            new = candidate.projects[i]
        scope = " ".join([orig.name, orig.description or "", *orig.tech, *orig.bullets]).lower()
        label = orig.name.split(":")[0]
        projects.append(
            orig.model_copy(
                update={
                    "bullets": bullets("projects", i, label, new.bullets if new else [], orig.bullets, scope),
                    "description": review(
                        "project_description", i, 0, label, new.description if new else None, orig.description, scope
                    ),
                    "tech": (truthful(new.tech) if new and orig.tech else []) or orig.tech,
                }
            )
        )

    groups = original.skill_groups
    if groups:
        new_groups = {_key(g.category): g for g in candidate.skill_groups}
        groups = [
            g.model_copy(update={"skills": truthful(new_groups[_key(g.category)].skills) or g.skills})
            if _key(g.category) in new_groups
            else g
            for g in original.skill_groups
        ]

    headline = review("headline", 0, 0, "Headline", candidate.contact.headline, original.contact.headline, evidence)
    locked = ResumeData(
        contact=original.contact.model_copy(update={"headline": headline}),
        summary=review("summary", 0, 0, "Summary", candidate.summary, original.summary, evidence),
        # With groups, the flat list is rebuilt from them; extras must still be truthful.
        skills=[] if groups else (truthful(candidate.skills) or original.skills),
        skill_groups=groups,
        experience=experience,
        projects=projects,
        education=original.education,
        certifications=original.certifications,
        extra_sections=original.extra_sections,
        section_order=original.section_order,
        layout=original.layout,
    )
    return locked, reviews


def apply_reviews(resume: ResumeData, reviews: list[BulletReview]) -> ResumeData:
    """Set each reviewed line to its suggestion (if applied) or the original."""
    out = resume.model_copy(deep=True)
    for r in reviews:
        text = r.suggested if r.applied else r.original
        if r.section == "experience" and r.entry < len(out.experience) and r.index < len(out.experience[r.entry].bullets):
            out.experience[r.entry].bullets[r.index] = text
        elif r.section == "projects" and r.entry < len(out.projects) and r.index < len(out.projects[r.entry].bullets):
            out.projects[r.entry].bullets[r.index] = text
        elif r.section == "project_description" and r.entry < len(out.projects):
            out.projects[r.entry].description = text
        elif r.section == "summary":
            out.summary = text
        elif r.section == "headline":
            out.contact.headline = text
    return out


Candidate = tuple[ResumeData, AtsReport, list[BulletReview]]


async def _one_candidate(
    prompt: str, temperature: float, role: str, job_description: str | None, original: ResumeData
) -> Candidate | str:
    """Generate and score a single tailored candidate; the error message on failure."""
    try:
        data = await complete_json(_TAILOR_SYSTEM, prompt, temperature=temperature, max_tokens=8192)
        candidate, reviews = lock_facts(original, ResumeData.model_validate(data))
    except (LlmError, ValueError, TypeError) as exc:
        log.warning("tailoring candidate failed: %s", exc)
        return str(exc)
    return candidate, score_resume(candidate, role, job_description), reviews


async def tailor_resume(
    resume: ResumeData,
    role: str,
    job_description: str | None = None,
    *,
    target_score: float = 90.0,
    max_iterations: int = 4,
    candidates: int | None = None,
) -> TailorResult:
    profile = get_role(role)
    keywords = target_keywords(role, job_description)
    n_candidates = candidates if candidates is not None else get_settings().llm.tailor_candidates
    n_candidates = max(1, n_candidates)

    best = resume
    best_report = score_resume(resume, role, job_description)
    iterations = 0

    if best_report.score >= target_score:
        return TailorResult(best, best_report, iterations)

    current = resume
    current_report = best_report
    best_reviews: list[BulletReview] = []
    # Highest-scoring candidate even if it doesn't beat the original: its
    # suggestions are still worth showing.
    top: Candidate | None = None
    warning: str | None = None
    for _ in range(max(1, max_iterations)):
        iterations += 1
        prompt = _build_user_prompt(
            current, profile.label, profile.emphasis, job_description, current_report, keywords
        )
        # Best-of-N: generate several candidates concurrently with varied
        # temperatures, then keep the highest scoring one.
        temps = [round(0.15 + 0.15 * i, 2) for i in range(n_candidates)]
        results = await asyncio.gather(
            *(_one_candidate(prompt, t, role, job_description, resume) for t in temps)
        )
        round_best: Candidate | None = None
        for res in results:
            if isinstance(res, str):
                continue
            if round_best is None or res[1].score > round_best[1].score:
                round_best = res

        if round_best is None:
            # No LLM or all candidates failed: return the best so far.
            if best is resume:
                warning = (
                    "AI rewriting failed, so this is your original resume, scored but "
                    f"not optimized. Check your LLM keys in Settings. ({results[0]})"
                )
            break

        candidate, candidate_report, reviews = round_best
        if top is None or candidate_report.score > top[1].score:
            top = round_best
        if candidate_report.score > best_report.score:
            best, best_report, best_reviews = candidate, candidate_report, reviews
        current, current_report = candidate, candidate_report
        if best_report.score >= target_score:
            break

    if best is resume and top is not None:
        # Nothing beat the original: keep it, but offer the suggestions unapplied.
        best_reviews = [r.model_copy(update={"applied": False}) for r in top[2]]
    return TailorResult(best, best_report, iterations, warning, best_reviews)
