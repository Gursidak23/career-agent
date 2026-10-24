"""When every LLM provider fails, features degrade *visibly* (with a warning)."""

import pytest

from app.llm import LlmError
from app.outreach import messages
from app.resume import parser, tailor
from app.schemas import ContactInfo, MessageGenRequest, ResumeData


async def _fail(*args, **kwargs):
    raise LlmError("All LLM providers failed; last error: 404 model not found")


@pytest.mark.asyncio
async def test_parser_fallback_returns_warning(monkeypatch):
    monkeypatch.setattr(parser, "complete_json", _fail)
    parsed, warning = await parser.structure_resume("Jane Doe\njane@example.com\nPython, SQL, Docker")
    assert parsed.contact.email == "jane@example.com"
    assert warning and "404 model not found" in warning


@pytest.mark.asyncio
async def test_parser_success_has_no_warning(monkeypatch):
    async def ok(*args, **kwargs):
        return {"contact": {"name": "Jane Doe"}, "skills": ["Python"]}

    monkeypatch.setattr(parser, "complete_json", ok)
    parsed, warning = await parser.structure_resume("Jane Doe")
    assert parsed.contact.name == "Jane Doe"
    assert warning is None


@pytest.mark.asyncio
async def test_tailor_without_llm_returns_original_with_warning(monkeypatch):
    monkeypatch.setattr(tailor, "complete_json", _fail)
    resume = ResumeData(contact=ContactInfo(name="Jane Doe"), skills=["Python"])
    result = await tailor.tailor_resume(resume, "software_developer", max_iterations=2, candidates=1)
    assert result.resume == resume
    assert result.warning and "not optimized" in result.warning


@pytest.mark.asyncio
async def test_messages_template_fallback_returns_warning(monkeypatch):
    monkeypatch.setattr(messages, "complete_json", _fail)
    out, warning = await messages.generate_messages(MessageGenRequest(company="Acme", role="SWE"))
    assert len(out) == 1 and "Acme" in out[0].body
    assert warning


@pytest.mark.asyncio
async def test_messages_accept_wrapped_object(monkeypatch):
    async def ok(*args, **kwargs):
        return {"messages": [{"channel": "email", "subject": "Hi", "body": "Hello Acme"}]}

    monkeypatch.setattr(messages, "complete_json", ok)
    out, warning = await messages.generate_messages(MessageGenRequest(company="Acme", role="SWE"))
    assert [m.body for m in out] == ["Hello Acme"]
    assert warning is None
