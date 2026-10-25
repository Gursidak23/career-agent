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
from .base import ChatMessage, LlmError, report_usage


def credits_today() -> float:
    """Copilot AI credits spent since local midnight, from the usage ledger."""
    from datetime import datetime, timezone

    from sqlalchemy import func, select

    from ..db import SessionLocal
    from ..models import LlmCall

    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    since = midnight.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        with SessionLocal() as db:
            total = db.scalar(
                select(func.sum(LlmCall.credits)).where(LlmCall.provider == "copilot", LlmCall.created_at >= since)
            )
    except Exception:  # noqa: BLE001 - no ledger yet (e.g. first start): don't block
        return 0.0
    return float(total or 0.0)


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
        budget = self._settings.copilot_daily_credit_budget
        spent = credits_today()
        if budget >= 0 and spent >= budget:
            raise LlmError(f"Copilot daily budget reached ({spent:.2f}/{budget:g} AI credits)")
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
            usage: list = []
            session.on(lambda e: usage.append(e.data) if type(e.data).__name__ == "AssistantUsageData" else None)
            try:
                resp = await session.send_and_wait(
                    prompt, timeout=self._settings.copilot_timeout_seconds
                )
            finally:
                await session.disconnect()
            nano = sum(getattr(getattr(u, "copilot_usage", None), "total_nano_aiu", 0) or 0 for u in usage)
            report_usage(
                sum(u.input_tokens or 0 for u in usage) or None,
                sum(u.output_tokens or 0 for u in usage) or None,
                nano / 1e9,
            )
        except LlmError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize provider errors
            raise LlmError(f"Copilot error: {exc}") from exc
        return getattr(getattr(resp, "data", None), "content", None) or ""
