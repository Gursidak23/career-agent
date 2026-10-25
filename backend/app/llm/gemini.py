"""Google Gemini client (free tier via AI Studio key) using google-genai async."""

from __future__ import annotations

import asyncio
from typing import Any

from ..config import LlmSettings
from .base import ChatMessage, LlmError, report_usage


def _to_gemini(messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, Any]]]:
    system = "\n\n".join(m.content for m in messages if m.role == "system") or None
    contents: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            continue
        role = "model" if message.role == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": message.content}]})
    return system, contents


class GeminiClient:
    name = "gemini"

    def __init__(self, settings: LlmSettings) -> None:
        self._settings = settings
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            if not self._settings.gemini_api_key:
                raise LlmError("Gemini API key is not configured (CAREER_LLM__GEMINI_API_KEY)")
            from google import genai

            self._client = genai.Client(api_key=self._settings.gemini_api_key)
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
        system, contents = _to_gemini(messages)
        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system,
            response_mime_type="application/json" if json_mode else None,
        )
        try:
            resp = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self._settings.gemini_model,
                    contents=contents,
                    config=config,
                ),
                self._settings.request_timeout_seconds,
            )
        except TimeoutError as exc:
            raise LlmError(
                f"Gemini timed out after {self._settings.request_timeout_seconds:.0f}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - normalize provider errors
            raise LlmError(f"Gemini error: {exc}") from exc
        usage = getattr(resp, "usage_metadata", None)
        if usage is not None:
            report_usage(
                getattr(usage, "prompt_token_count", None),
                (getattr(usage, "candidates_token_count", None) or 0) + (getattr(usage, "thoughts_token_count", None) or 0),
            )
        return resp.text or ""
