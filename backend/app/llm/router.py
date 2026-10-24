"""Build the fallback LLM client from settings and expose helpers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..config import LlmSettings, get_settings
from .base import ChatMessage, LlmClient, extract_json
from .cache import LlmCache, make_key
from .copilot import CopilotClient
from .fallback import FallbackLlmClient
from .gemini import GeminiClient
from .groq import GroqClient
from .ratelimit import TokenBucket

# Fixed fallback order: Gemini -> Groq -> Copilot (paid, so last).
# (GitHub Models was retired 2026-07-30.)
_PROVIDER_ORDER = ("gemini", "groq", "copilot")


def _provider_configured(name: str, llm: LlmSettings) -> bool:
    return {
        "gemini": bool(llm.gemini_api_key),
        "groq": bool(llm.groq_api_key),
        "copilot": bool(llm.copilot_github_token),
    }.get(name, False)


def _provider_model(name: str, llm: LlmSettings) -> str:
    return {
        "gemini": llm.gemini_model,
        "groq": llm.groq_model,
        "copilot": llm.copilot_model or "default",
    }.get(name, "")


def available_providers() -> list[tuple[str, bool, str]]:
    """Return (name, configured, model) for each provider in fallback order."""
    llm = get_settings().llm
    return [
        (name, _provider_configured(name, llm), _provider_model(name, llm))
        for name in _PROVIDER_ORDER
    ]


def _build_clients(llm: LlmSettings) -> list[LlmClient]:
    clients: list[LlmClient] = []
    for name in _PROVIDER_ORDER:
        if not _provider_configured(name, llm):
            continue
        if name == "gemini":
            clients.append(GeminiClient(llm))
        elif name == "groq":
            clients.append(GroqClient(llm))
        elif name == "copilot":
            clients.append(CopilotClient(llm))
    return clients


@lru_cache
def get_llm() -> FallbackLlmClient:
    llm = get_settings().llm
    return FallbackLlmClient(_build_clients(llm), max_retries=llm.max_retries)


@lru_cache
def get_cache() -> LlmCache:
    settings = get_settings()
    llm = settings.llm
    persist = str(settings.data_path / "llm_cache.sqlite") if llm.cache_persist else None
    return LlmCache(
        enabled=llm.cache_enabled,
        ttl_seconds=llm.cache_ttl_seconds,
        persist_path=persist,
    )


@lru_cache
def get_bucket() -> TokenBucket:
    return TokenBucket(get_settings().llm.rate_per_minute)


async def aclose_llm() -> None:
    """Stop background provider processes (the Copilot runtime), if ever started."""
    if get_llm.cache_info().currsize:
        for client in get_llm().clients:
            close = getattr(client, "aclose", None)
            if close is not None:
                await close()


def reset_llm_cache() -> None:
    get_llm.cache_clear()
    get_cache.cache_clear()
    get_bucket.cache_clear()


async def complete(
    system: str,
    user: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> str:
    llm = get_settings().llm
    client = get_llm()
    temp = llm.temperature if temperature is None else temperature
    tokens = llm.max_output_tokens if max_tokens is None else max_tokens

    cache = get_cache()
    # Models are part of the key so switching models never serves stale answers;
    # json_mode too, so plain/JSON variants don't collide.
    chain = "|".join(f"{n}:{_provider_model(n, llm)}" for n in client.provider_names)
    key = make_key(chain, system, f"{json_mode}\x00{user}", temp, tokens)
    cached = cache.get(key)
    if cached is not None:
        return cached

    await get_bucket().acquire()
    text = await client.complete(
        [ChatMessage("system", system), ChatMessage("user", user)],
        temperature=temp,
        max_tokens=tokens,
        json_mode=json_mode,
    )
    cache.set(key, text)
    return text


async def complete_json(
    system: str,
    user: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Any:
    """Run a completion in native JSON mode and parse the response."""
    text = await complete(
        system, user, temperature=temperature, max_tokens=max_tokens, json_mode=True
    )
    return extract_json(text)
