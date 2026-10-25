"""Common LLM abstractions: chat messages, errors, and the client Protocol."""

from __future__ import annotations

import json
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class ChatMessage:
    role: str  # system | user | assistant
    content: str


class LlmError(RuntimeError):
    """Raised when a provider call fails (network, auth, rate limit, timeout)."""


@dataclass
class CallInfo:
    """Filled in during one completion: who served it and what it used."""

    provider: str | None = None
    model: str | None = None
    fallbacks: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    credits: float = 0.0
    errors: list[str] = field(default_factory=list)


# Per-call scratchpad. Context-local, so concurrent candidates don't mix.
_CALL: ContextVar[CallInfo | None] = ContextVar("llm_call", default=None)


def current_call() -> CallInfo:
    """The CallInfo of the completion in progress (a throwaway one outside a call)."""
    return _CALL.get() or CallInfo()


def start_call() -> tuple[CallInfo, object]:
    info = CallInfo()
    return info, _CALL.set(info)


def end_call(token: object) -> None:
    _CALL.reset(token)  # type: ignore[arg-type]


def report_usage(input_tokens: int | None, output_tokens: int | None, credits: float = 0.0) -> None:
    info = current_call()
    info.input_tokens, info.output_tokens, info.credits = input_tokens, output_tokens, credits


@runtime_checkable
class LlmClient(Protocol):
    name: str

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str: ...


_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Best-effort parse of a JSON object/array from an LLM response.

    Handles raw JSON, ```json fenced blocks, and leading/trailing prose.
    """
    text = (text or "").strip()
    if not text:
        raise LlmError("LLM returned empty output where JSON was expected")

    candidates: list[str] = []
    fenced = _JSON_FENCE.findall(text)
    candidates.extend(fenced)
    candidates.append(text)

    # Also try to slice from the first { or [ to its matching last bracket.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    raise LlmError("Could not parse JSON from LLM output")
