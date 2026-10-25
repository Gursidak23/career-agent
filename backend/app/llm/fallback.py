"""Resilience wrapper: retry each provider, then fail over to the next.

Free tiers are rate-limited, so the system must degrade gracefully. ``complete``
retries each provider with exponential backoff before moving on to the next one
in the chain.
"""

from __future__ import annotations

import asyncio

from ..logging_setup import get_logger
from .base import ChatMessage, LlmClient, LlmError, current_call

log = get_logger(__name__)


class FallbackLlmClient:
    def __init__(self, clients: list[LlmClient], *, max_retries: int = 3) -> None:
        if not clients:
            raise LlmError(
                "No LLM providers configured. Set at least one of "
                "CAREER_LLM__GEMINI_API_KEY, CAREER_LLM__GROQ_API_KEY, "
                "or CAREER_LLM__COPILOT_GITHUB_TOKEN."
            )
        self._clients = clients
        self._max_retries = max(1, max_retries)
        self.name = clients[0].name

    @property
    def clients(self) -> list[LlmClient]:
        return list(self._clients)

    @property
    def provider_names(self) -> list[str]:
        return [c.name for c in self._clients]

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        last_error: Exception | None = None
        info = current_call()
        for position, client in enumerate(self._clients):
            for attempt in range(self._max_retries):
                try:
                    text = await client.complete(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=json_mode,
                    )
                    info.provider = client.name
                    return text
                except Exception as exc:  # noqa: BLE001 - retry/fail over on any error
                    last_error = exc
                    # Budget/config refusals won't change on retry.
                    if "budget" in str(exc).lower() or "not configured" in str(exc).lower():
                        break
                    if attempt + 1 < self._max_retries:
                        await asyncio.sleep(0.5 * (2**attempt))
            info.errors.append(f"{client.name}: {last_error}")
            info.fallbacks += 1
            if position + 1 < len(self._clients):
                nxt = self._clients[position + 1]
                log.warning("llm fallback %s -> %s (%s)", client.name, nxt.name, last_error)
        raise LlmError(f"All LLM providers failed; last error: {last_error}")
