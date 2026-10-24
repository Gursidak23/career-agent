"""LLM providers (Gemini, Groq, Copilot) behind a common interface.

The public entry point is :func:`router.get_llm`, which returns a fallback
client trying providers in order: gemini -> groq -> copilot.
"""

from .base import ChatMessage, LlmClient, LlmError
from .router import available_providers, get_llm

__all__ = [
    "ChatMessage",
    "LlmClient",
    "LlmError",
    "get_llm",
    "available_providers",
]
