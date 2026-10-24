"""GitHub Copilot client via the official Copilot SDK (``github-copilot-sdk``).

Authenticates with a fine-grained PAT that has the "Copilot Requests" permission.
The SDK drives a local Copilot runtime (downloaded and cached on first use), so
each session replaces the runtime's agent system prompt with ours and disables
all tools: Copilot acts as a plain chat model and costs ~100x less per call.
Sampling knobs (temperature, max_tokens) are not exposed by the SDK and are
ignored. Billed against the account's Copilot AI credits.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..config import LlmSettings, get_settings
from .base import ChatMessage, LlmError


def _deny_all(request: Any, invocation: Any) -> Any:
    from copilot.generated.rpc import PermissionDecisionReject

    return PermissionDecisionReject(feedback="Tools are disabled.")


class CopilotClient:
    name = "copilot"

    def __init__(self, settings: LlmSettings) -> None:
        self._settings = settings
        self._client: Any = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> Any:
        async with self._lock:
            if self._client is None:
                if not self._settings.copilot_github_token:
                    raise LlmError(
                        "Copilot token is not configured (CAREER_LLM__COPILOT_GITHUB_TOKEN)"
                    )
                from copilot import CopilotClient as SdkClient

                # Empty working dir: the runtime gets no access to the project.
                workdir = get_settings().data_path / "copilot"
                workdir.mkdir(parents=True, exist_ok=True)
                client = SdkClient(
                    github_token=self._settings.copilot_github_token,
                    working_directory=str(workdir),
                    log_level="error",
                )
                await client.start()
                self._client = client
            return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.stop()
            self._client = None

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool = False,
    ) -> str:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        prompt = "\n\n".join(m.content for m in messages if m.role != "system")
        if json_mode:
            system += "\n\nRespond with valid JSON only, no prose or code fences."
        try:
            client = await self._get_client()
            session = await client.create_session(
                on_permission_request=_deny_all,
                model=self._settings.copilot_model or None,
                system_message={"mode": "replace", "content": system},
                available_tools=[],
            )
            try:
                resp = await session.send_and_wait(
                    prompt, timeout=self._settings.copilot_timeout_seconds
                )
            finally:
                await session.disconnect()
        except LlmError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize provider errors
            raise LlmError(f"Copilot error: {exc}") from exc
        return getattr(getattr(resp, "data", None), "content", None) or ""
