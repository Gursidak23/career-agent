"""Groq client (free tier, OpenAI-compatible) using the async SDK."""

from __future__ import annotations

from typing import Any

from ..config import LlmSettings
from .base import ChatMessage, LlmError, report_usage


def _to_openai(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in messages]


class GroqClient:
    name = "groq"

    def __init__(self, settings: LlmSettings) -> None:
        self._settings = settings
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._settings.groq_api_key:
                raise LlmError("Groq API key is not configured (CAREER_LLM__GROQ_API_KEY)")
            from groq import AsyncGroq

            self._client = AsyncGroq(
                api_key=self._settings.groq_api_key,
                timeout=self._settings.request_timeout_seconds,
            )
        return self._client

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        client = self._get_client()
        kwargs: dict = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await client.chat.completions.create(
                model=self._settings.groq_model,
                messages=_to_openai(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
        except Exception as exc:  # noqa: BLE001 - normalize provider errors
            raise LlmError(f"Groq error: {exc}") from exc
        usage = getattr(resp, "usage", None)
        if usage is not None:
            report_usage(getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None))
        return resp.choices[0].message.content or ""
