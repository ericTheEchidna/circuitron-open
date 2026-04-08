"""LLM provider implementations for Circuitron."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..provider import LLMProvider

if TYPE_CHECKING:
    from ..settings import Settings


def get_provider(settings: "Settings") -> LLMProvider:
    """Return a :class:`~circuitron.provider.LLMProvider` for the configured backend.

    Args:
        settings: The active :class:`~circuitron.settings.Settings` instance.

    Returns:
        A concrete provider matching ``settings.provider``.

    Raises:
        ValueError: If ``settings.provider`` names an unknown backend.
    """
    if settings.provider == "openai-agents":
        from .openai_agents import OpenAIAgentsProvider

        return OpenAIAgentsProvider()

    if settings.provider == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider()

    if settings.provider == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider()

    raise ValueError(
        f"Unknown provider {settings.provider!r}. "
        "Set CIRCUITRON_PROVIDER to a supported value "
        "('openai-agents' or 'anthropic')."
    )


__all__ = ["get_provider"]
