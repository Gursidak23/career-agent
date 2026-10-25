"""Generate cold outreach messages (email + LinkedIn DM) via the LLM.

Falls back to a clean template if no LLM is configured, so message generation
always returns something usable.
"""

from __future__ import annotations

from ..llm import LlmError
from ..llm.router import complete_json
from ..logging_setup import get_logger
from ..schemas import GeneratedMessage, MessageGenRequest

log = get_logger(__name__)

_SYSTEM = (
    "You are an expert career coach who writes concise, personalized, high-response "
    "cold outreach messages to recruiters and hiring managers. Messages are specific, "
    "respectful, and never spammy. Email bodies are 90-140 words; LinkedIn DMs are "
    "under 60 words (connection-request friendly). Always return ONLY a JSON object."
)


def _user_prompt(req: MessageGenRequest) -> str:
    highlights = "; ".join(req.candidate_highlights) if req.candidate_highlights else "(none provided)"
    posting = ""
    if req.job_description:
        posting = f'\nJob posting (excerpt):\n"""\n{req.job_description[:2500]}\n"""\n'
    return f"""
Write {req.variants} distinct {req.channel} outreach message variants.

Recruiter name: {req.recruiter_name or "(unknown - use a polite generic greeting)"}
Company: {req.company}
Role applying for: {req.role}
Candidate name: {req.candidate_name or "(the applicant)"}
Candidate highlights: {highlights}
Tone: {req.tone}
{posting}
Return a JSON object {{"messages": [...]}}; each element of "messages":
{{"channel": "{req.channel}", "subject": str|null, "body": str}}
For LinkedIn DMs set "subject" to null. For emails include a compelling subject.
Personalize to the company/role, connecting the candidate's highlights to what the
posting asks for. Do not fabricate facts about the candidate beyond the highlights,
and never claim knowledge of the company's news, products, or achievements unless
they appear in the job posting above.
""".strip()


def _fallback(req: MessageGenRequest) -> list[GeneratedMessage]:
    greeting = f"Hi {req.recruiter_name}," if req.recruiter_name else "Hello,"
    hl = ""
    if req.candidate_highlights:
        hl = " " + " ".join(req.candidate_highlights[:2])
    if req.channel == "linkedin":
        body = (
            f"{greeting} I'm very interested in the {req.role} role at {req.company}."
            f"{hl} Would love to connect and learn more about the team."
        )
        return [GeneratedMessage(channel="linkedin", subject=None, body=body)]
    subject = f"Application for {req.role} at {req.company}"
    body = (
        f"{greeting}\n\n"
        f"I'm reaching out about the {req.role} position at {req.company}. "
        f"I bring relevant experience that maps closely to this role.{hl}\n\n"
        f"I'd welcome the chance to share how I can contribute. I've attached my resume "
        f"and would be happy to talk at your convenience.\n\n"
        f"Best regards,\n{req.candidate_name or ''}"
    )
    return [GeneratedMessage(channel="email", subject=subject, body=body)]


def _unwrap(data: object) -> object:
    """Accept {"messages": [...]} (requested shape), a bare list, or a single message."""
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
        return [data]
    return data


async def generate_messages(req: MessageGenRequest) -> tuple[list[GeneratedMessage], str | None]:
    """Return ``(messages, warning)``; ``warning`` is set when the template fallback was used."""
    try:
        data = await complete_json(_SYSTEM, _user_prompt(req), temperature=0.5, max_tokens=4096, purpose="outreach")
        data = _unwrap(data)
        if isinstance(data, list):
            out = [GeneratedMessage.model_validate(m) for m in data if isinstance(m, dict)]
            if out:
                return out, None
        reason = "LLM returned no usable messages"
    except (LlmError, ValueError, TypeError) as exc:
        reason = str(exc)
    log.warning("message generation fell back to template: %s", reason)
    warning = (
        "AI generation failed, so a generic template was used. "
        f"Check your LLM keys in Settings. ({reason})"
    )
    return _fallback(req), warning
