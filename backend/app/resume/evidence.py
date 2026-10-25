"""Requirement-by-requirement evidence: what a job asks for vs. what you can prove.

The LLM splits a posting into must-have / nice-to-have requirements and maps each
to lines of the resume. It sees the resume as numbered lines and may only cite
line numbers, so evidence can't be invented: unknown ids are dropped, and a
requirement marked "met" without a valid citation is downgraded to a gap.
Red flags combine the LLM's reading with a deterministic check of the posting's
"N+ years" demand against the experience dates on the resume.
"""

from __future__ import annotations

import re
from datetime import date

from ..llm import LlmError
from ..llm.router import complete_json
from ..logging_setup import get_logger
from ..schemas import EvidenceLine, EvidenceReport, RedFlag, Requirement, ResumeData

log = get_logger(__name__)

_SYSTEM = (
    "You analyze job postings for a candidate. You are precise and honest: you never "
    "claim the candidate meets a requirement unless a cited resume line clearly shows it. "
    "Return ONLY a JSON object."
)

_RULES = """
Return {"requirements": [...], "red_flags": [...]} where:
- requirements: the distinct skills, experience and qualifications the posting asks
  for (at most 15, most important first). Each:
  {"text": short requirement, "kind": "must" | "nice", "evidence": [resume line
  numbers that directly demonstrate it], "status": "met" | "partial" | "gap",
  "note": one short sentence}
  * "must" if required/essential; "nice" if preferred, a plus, bonus, or nice to have.
  * status "met" only if the cited lines clearly satisfy it; "partial" if related but
    weaker; "gap" if nothing in the resume shows it. Cite only line numbers shown.
  * note: for met/partial, what the evidence proves; for gaps, an honest way to
    address it (related experience to mention, or what to learn). Never suggest
    claiming experience the candidate does not have.
- red_flags: genuine concerns stated in the posting itself (at most 5), e.g.
  experience demands inconsistent with the level, unpaid trial work, extreme hours,
  no compensation information, one role covering several unrelated jobs.
  Each {"text": short flag, "why": one sentence}. Empty if none.
""".strip()

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_YEARS_ASKED = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs)", re.IGNORECASE)


def resume_lines(resume: ResumeData) -> list[EvidenceLine]:
    """Every citable line of the resume, labelled with where it sits."""
    lines: list[EvidenceLine] = []

    def add(where: str, text: str | None) -> None:
        if text and text.strip():
            lines.append(EvidenceLine(id=len(lines) + 1, where=where, text=text.strip()))

    add("Headline", resume.contact.headline)
    add("Summary", resume.summary)
    for e in resume.experience:
        add(f"{e.title}, {e.company}", f"{e.title} at {e.company}")
        for b in e.bullets:
            add(e.company, b)
    for p in resume.projects:
        name = p.name.split(":")[0]
        add(f"Project: {name}", p.name)
        for b in p.bullets:
            add(f"Project: {name}", b)
    if resume.skill_groups:
        for g in resume.skill_groups:
            add("Skills", f"{g.category}: {', '.join(g.skills)}")
    elif resume.skills:
        add("Skills", ", ".join(resume.skills))
    for ed in resume.education:
        add("Education", " | ".join(x for x in (ed.degree, ed.institution, ed.details) if x))
    for c in resume.certifications:
        add("Certifications", c.name)
    for x in resume.extra_sections:
        for item in x.items:
            add(x.title.title(), item)
    return lines


def _month(text: str | None, today: date) -> tuple[int, int] | None:
    if not text:
        return None
    t = text.strip().lower()
    if t in ("present", "current", "now", "today"):
        return today.year, today.month
    m = re.search(r"([a-z]{3})[a-z]*\.?\s+(\d{4})", t)
    if m and m.group(1) in _MONTHS:
        return int(m.group(2)), _MONTHS[m.group(1)]
    y = re.search(r"\b(19|20)\d{2}\b", t)
    return (int(y.group(0)), 6) if y else None


def candidate_years(resume: ResumeData, today: date | None = None) -> float:
    """Professional experience in years from the experience dates (internships count half)."""
    today = today or date.today()
    total = 0.0
    for e in resume.experience:
        start, end = _month(e.start_date, today), _month(e.end_date or "present", today)
        if not start or not end:
            continue
        months = max(0, (end[0] - start[0]) * 12 + end[1] - start[1])
        total += months / 12 * (0.5 if "intern" in e.title.lower() else 1.0)
    return round(total, 1)


def years_required(job_description: str) -> int | None:
    found = [int(n) for n in _YEARS_ASKED.findall(job_description or "") if 0 < int(n) <= 20]
    return min(found) if found else None


async def analyze(resume: ResumeData, job_description: str) -> EvidenceReport:
    lines = resume_lines(resume)
    numbered = "\n".join(f"[{ln.id}] ({ln.where}) {ln.text}" for ln in lines)
    by_id = {ln.id: ln for ln in lines}
    prompt = (
        f'JOB POSTING:\n"""\n{job_description[:6000]}\n"""\n\n'
        f"RESUME LINES:\n{numbered}\n\n{_RULES}"
    )
    try:
        data = await complete_json(_SYSTEM, prompt, temperature=0.0, max_tokens=4096, purpose="evidence")
    except LlmError as exc:
        raise ValueError(f"AI analysis failed: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("AI analysis returned an unexpected shape")

    requirements: list[Requirement] = []
    for raw in data.get("requirements") or []:
        if not isinstance(raw, dict) or not str(raw.get("text", "")).strip():
            continue
        ids = []
        for x in raw.get("evidence") or []:
            try:
                ids.append(int(str(x).strip("[] L")))
            except ValueError:
                continue
        evidence = [by_id[i] for i in dict.fromkeys(ids) if i in by_id]
        status = raw.get("status") if raw.get("status") in ("met", "partial", "gap") else "gap"
        note = str(raw.get("note") or "")
        if status != "gap" and not evidence:
            status, note = "gap", "No resume line shows this. " + note
        if status == "gap":
            evidence = []  # a gap has no proof; related lines belong in the note
        requirements.append(
            Requirement(
                text=str(raw["text"]).strip()[:200],
                kind="nice" if raw.get("kind") == "nice" else "must",
                status=status,
                evidence=evidence,
                note=note[:300],
            )
        )

    flags = [
        RedFlag(text=str(f.get("text", ""))[:160], why=str(f.get("why", ""))[:300])
        for f in data.get("red_flags") or []
        if isinstance(f, dict) and f.get("text")
    ]
    have, asked = candidate_years(resume), years_required(job_description)
    if asked is not None and asked > have + 1:
        flags.insert(
            0,
            RedFlag(
                text=f"Asks for {asked}+ years; you have about {have:g}",
                why="Apply anyway if the rest fits well, but lead with your strongest evidence.",
            ),
        )

    musts = [r for r in requirements if r.kind == "must"]
    nices = [r for r in requirements if r.kind == "nice"]
    return EvidenceReport(
        requirements=sorted(requirements, key=lambda r: (r.kind != "must", ["gap", "partial", "met"].index(r.status))),
        red_flags=flags,
        must_met=sum(r.status == "met" for r in musts),
        must_total=len(musts),
        nice_met=sum(r.status == "met" for r in nices),
        nice_total=len(nices),
        years_required=asked,
        years_candidate=have,
    )
