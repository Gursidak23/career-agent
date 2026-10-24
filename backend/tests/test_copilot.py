import pytest

from app.config import LlmSettings
from app.llm import LlmError
from app.llm.base import ChatMessage
from app.llm.copilot import CopilotClient
from app.llm.router import _build_clients


class _Reply:
    def __init__(self, content: str) -> None:
        self.data = type("Data", (), {"content": content})()


class _FakeSession:
    def __init__(self, reply: str | Exception) -> None:
        self._reply = reply
        self.prompt: str | None = None
        self.disconnected = False

    async def send_and_wait(self, prompt, *, timeout):
        self.prompt = prompt
        if isinstance(self._reply, Exception):
            raise self._reply
        return _Reply(self._reply)

    async def disconnect(self):
        self.disconnected = True


class _FakeSdk:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.kwargs: dict = {}

    async def create_session(self, **kwargs):
        self.kwargs = kwargs
        return self.session


def _client(sdk: _FakeSdk, **settings) -> CopilotClient:
    client = CopilotClient(LlmSettings(copilot_github_token="github_pat_x", **settings))

    async def _get():
        return sdk

    client._get_client = _get
    return client


_MSGS = [ChatMessage("system", "Be a JSON API."), ChatMessage("user", "hi")]


@pytest.mark.asyncio
async def test_replaces_system_prompt_and_disables_tools():
    sdk = _FakeSdk(_FakeSession('{"ok": true}'))
    out = await _client(sdk).complete(_MSGS, temperature=0.2, max_tokens=100, json_mode=True)
    assert out == '{"ok": true}'
    assert sdk.kwargs["available_tools"] == []
    assert sdk.kwargs["system_message"]["mode"] == "replace"
    assert sdk.kwargs["system_message"]["content"].startswith("Be a JSON API.")
    assert sdk.kwargs["model"] is None  # blank model -> account default
    assert sdk.session.prompt == "hi"
    assert sdk.session.disconnected


@pytest.mark.asyncio
async def test_errors_normalized_and_session_closed():
    sdk = _FakeSdk(_FakeSession(TimeoutError("slow")))
    with pytest.raises(LlmError, match="Copilot error"):
        await _client(sdk).complete(_MSGS, temperature=0.2, max_tokens=100)
    assert sdk.session.disconnected


@pytest.mark.asyncio
async def test_missing_token_raises_llm_error():
    with pytest.raises(LlmError, match="not configured"):
        await CopilotClient(LlmSettings()).complete(_MSGS, temperature=0.2, max_tokens=100)


def test_copilot_is_last_in_chain():
    llm = LlmSettings(gemini_api_key="g", groq_api_key="q", copilot_github_token="c")
    assert [c.name for c in _build_clients(llm)] == ["gemini", "groq", "copilot"]
    assert [c.name for c in _build_clients(LlmSettings(gemini_api_key="g"))] == ["gemini"]
