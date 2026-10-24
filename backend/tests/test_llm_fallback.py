import pytest

from app.llm.base import ChatMessage, LlmError, extract_json
from app.llm.fallback import FallbackLlmClient


class _Stub:
    def __init__(self, name: str, *, fail: bool = False, reply: str = "ok") -> None:
        self.name = name
        self._fail = fail
        self._reply = reply
        self.calls = 0

    async def complete(self, messages, *, temperature, max_tokens, json_mode=False):
        self.calls += 1
        if self._fail:
            raise LlmError(f"{self.name} boom")
        return self._reply


@pytest.mark.asyncio
async def test_primary_used_when_healthy():
    primary = _Stub("gemini", reply="from-gemini")
    secondary = _Stub("groq", reply="from-groq")
    client = FallbackLlmClient([primary, secondary], max_retries=2)
    out = await client.complete([ChatMessage("user", "hi")], temperature=0.0, max_tokens=10)
    assert out == "from-gemini"
    assert secondary.calls == 0


@pytest.mark.asyncio
async def test_falls_over_to_secondary():
    primary = _Stub("gemini", fail=True)
    secondary = _Stub("groq", reply="from-groq")
    client = FallbackLlmClient([primary, secondary], max_retries=2)
    out = await client.complete([ChatMessage("user", "hi")], temperature=0.0, max_tokens=10)
    assert out == "from-groq"
    assert primary.calls == 2  # retried max_retries before failover


@pytest.mark.asyncio
async def test_all_fail_raises():
    a = _Stub("gemini", fail=True)
    b = _Stub("groq", fail=True)
    client = FallbackLlmClient([a, b], max_retries=1)
    with pytest.raises(LlmError):
        await client.complete([ChatMessage("user", "hi")], temperature=0.0, max_tokens=10)


def test_no_providers_raises():
    with pytest.raises(LlmError):
        FallbackLlmClient([])


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('Here you go: {"a": 3} thanks') == {"a": 3}
    assert extract_json('[1, 2, 3]') == [1, 2, 3]
