"""Defend-your-resume drill: a skeptical interviewer questions every claim.

Bullets with numbers come first, because that is what interviewers probe ("How
did you measure 50%? Against what baseline?"). Each answer is graded as
defended / shaky / undefended, with feedback, a follow-up question, and, for
claims you couldn't back up, safer wording that claims only what your answer
supports. Safer wording may not introduce technologies the claim and answer
don't mention.
"""

from __future__ import annotations

import re

from ..llm import LlmError
from ..llm.router import complete_json
from ..schemas import DrillClaim, DrillGrade, DrillQuestion, ResumeData
from .ats import unsupported_terms

_DIGIT = re.compile(r"\d")

_ASK_SYSTEM = (
    "You are a skeptical senior engineering interviewer. You probe resume claims to "
    "find out whether the candidate really did the work and understands it. Return ONLY JSON."
)

_GRADE_SYSTEM = (
    "You grade a candidate's spoken-style answer defending one resume claim. You are "
    "fair but strict: vague answers, missing baselines, or 'we' without the candidate's "
    "own role are weaknesses. Return ONLY JSON."
)


def claims(resume: ResumeData, count: int = 6) -> list[DrillClaim]:
    """The bullets to grill: quantified ones first, spread across entries."""
    items: list[DrillClaim] = []
    for e in resume.experience:
        for b in e.bullets:
            items.append(DrillClaim(id=len(items) + 1, where=f"{e.title}, {e.company}", text=b))
    for p in resume.projects:
        for b in p.bullets:
            items.append(DrillClaim(id=len(items) + 1, where=f"Project: {p.name.split(':')[0]}", text=b))
    quantified = [c for c in items if _DIGIT.search(c.text)]
    rest = [c for c in items if not _DIGIT.search(c.text)]
    return (quantified + rest)[: max(1, count)]


async def questions(resume: ResumeData, count: int = 6) -> list[DrillQuestion]:
    picked = claims(resume, count)
    listing = "\n".join(f"[{c.id}] ({c.where}) {c.text}" for c in picked)
    prompt = f"""
Resume claims:
{listing}

For EACH claim write ONE probing interview question that tests whether the candidate
really did this and can explain it: how a number was measured and against what
baseline, their personal contribution versus the team's, the key design decision or
trade-off, or what went wrong. Make it specific to the claim, not generic.
Also list 2-4 things a strong answer would cover.

Return {{"questions": [{{"claim_id": int, "question": str, "look_for": [str]}}]}}
""".strip()
    try:
        data = await complete_json(_ASK_SYSTEM, prompt, temperature=0.3, max_tokens=3000, purpose="drill")
    except LlmError as exc:
        raise ValueError(f"AI question generation failed: {exc}") from exc
    by_id = {c.id: c for c in picked}
    out: list[DrillQuestion] = []
    for q in (data.get("questions") if isinstance(data, dict) else None) or []:
        try:
            claim = by_id[int(q.get("claim_id"))]
        except (KeyError, TypeError, ValueError):
            continue
        if not str(q.get("question") or "").strip():
            continue
        out.append(
            DrillQuestion(
                claim_id=claim.id,
                where=claim.where,
                claim=claim.text,
                question=str(q["question"]).strip(),
                look_for=[str(x) for x in (q.get("look_for") or [])][:4],
            )
        )
    return out


async def grade(claim: str, question: str, look_for: list[str], answer: str) -> DrillGrade:
    if len(answer.split()) < 4:
        return DrillGrade(
            verdict="undefended",
            score=1,
            feedback="That's too short to defend the claim. Say what you did, how you measured it, and the result.",
        )
    prompt = f"""
Claim on the resume: "{claim}"
Interviewer's question: "{question}"
A strong answer covers: {"; ".join(look_for) or "specifics, measurement, own role"}
Candidate's answer: \"\"\"{answer[:3000]}\"\"\"

Return {{"verdict": "defended" | "shaky" | "undefended", "score": 1-5,
"feedback": "2 short sentences: what worked and what was missing",
"follow_up": "the next question an interviewer would ask, or null",
"safer_wording": "only if shaky or undefended: the resume bullet rewritten to claim
only what this answer actually supports, otherwise null"}}
The safer wording must not add any fact, number or technology that is not in the
claim or the answer.
""".strip()
    try:
        data = await complete_json(_GRADE_SYSTEM, prompt, temperature=0.0, max_tokens=1200, purpose="drill")
    except LlmError as exc:
        raise ValueError(f"AI grading failed: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("AI grading returned an unexpected shape")

    verdict = data.get("verdict") if data.get("verdict") in ("defended", "shaky", "undefended") else "shaky"
    try:
        score = max(1, min(5, int(data.get("score") or 3)))
    except (TypeError, ValueError):
        score = 3
    safer = str(data.get("safer_wording") or "").strip() or None
    if verdict == "defended":
        safer = None
    elif safer:
        source = f"{claim} {answer}".lower()
        if unsupported_terms(safer.lower(), source, source):
            safer = None  # the "safer" version claimed something new: drop it
    follow = str(data.get("follow_up") or "").strip() or None
    return DrillGrade(
        verdict=verdict,
        score=score,
        feedback=str(data.get("feedback") or "")[:600],
        follow_up=None if follow in (None, "null") else follow,
        safer_wording=safer,
    )
