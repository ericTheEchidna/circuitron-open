"""Ollama provider — local LLM backend via the OpenAI-compatible REST API.

Requires a running Ollama instance.  Set ``CIRCUITRON_PROVIDER=ollama`` and
optionally ``OLLAMA_BASE_URL`` (default: ``http://localhost:11434``).  No API
key is needed; Circuitron passes ``"ollama"`` as a placeholder.

Usage::

    CIRCUITRON_PROVIDER=ollama \\
    OLLAMA_BASE_URL=http://localhost:11434 \\
    circuitron "design a 5V buck converter"
"""

from __future__ import annotations

import logging
import warnings
from typing import Any

from .openai_agents import OpenAIAgentsProvider

logger = logging.getLogger(__name__)

# Models known to support parallel function/tool calling in Ollama.
# Prefixes are matched against the model name (before the first colon).
_TOOL_CAPABLE_PREFIXES: frozenset[str] = frozenset(
    {
        "qwen2.5-coder",
        "qwen2.5",
        "qwen3",
        "llama3.1",
        "llama3.2",
        "llama3.3",
        "mistral-nemo",
        "mistral-small",
        "mistral",
        "functionary",
        "hermes3",
        "command-r",
        "command-r-plus",
        "firefunction",
        "nexusraven",
    }
)


def _model_base(name: str) -> str:
    """Return the model family prefix (part before the first colon)."""
    return name.split(":")[0].lower()


class OllamaProvider(OpenAIAgentsProvider):
    """``LLMProvider`` backed by Ollama via the OpenAI-compatible ``/v1`` API.

    Inherits the full OpenAI Agents SDK implementation from
    :class:`~circuitron.providers.openai_agents.OpenAIAgentsProvider` and
    re-points the SDK client at the local Ollama endpoint.

    On initialisation:
    - Creates an ``openai.AsyncOpenAI`` client aimed at ``{base_url}/v1``
    - Registers it as the default client for the Agents SDK
    - Fetches the list of pulled models from Ollama and warns if any
      configured model is not known to support tool/function calling
    """

    def __init__(self) -> None:
        from ..config import settings

        base_url: str = settings.ollama_base_url.rstrip("/")
        self._base_url = base_url

        # Point the OpenAI Agents SDK at the local Ollama endpoint.
        try:
            import openai
            from agents import set_default_openai_client  # type: ignore[attr-defined]

            client = openai.AsyncOpenAI(
                base_url=f"{base_url}/v1",
                api_key="ollama",
            )
            set_default_openai_client(client)
            logger.debug("OllamaProvider: set default openai client → %s/v1", base_url)
        except (ImportError, AttributeError):
            # Fallback: set environment variables so the SDK picks them up
            import os

            os.environ["OPENAI_BASE_URL"] = f"{base_url}/v1"
            os.environ["OPENAI_API_KEY"] = "ollama"
            logger.debug(
                "OllamaProvider: set_default_openai_client unavailable — "
                "fell back to env vars (OPENAI_BASE_URL, OPENAI_API_KEY)"
            )

        self._available_models: list[str] = self._fetch_model_names(base_url)
        self._warn_non_tool_models(settings)

    # ------------------------------------------------------------------
    # Override: tracing — instrument via the OpenAI Agents SDK (no extra
    # Ollama-specific instrumentation needed).
    # ------------------------------------------------------------------

    @staticmethod
    def configure_tracing() -> None:
        """Instrument the OpenAI Agents SDK with Logfire (Ollama re-uses it)."""
        try:
            import importlib

            logfire = importlib.import_module("logfire")
            logfire.instrument_openai_agents()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Override: cost — all Ollama models are free (local inference).
    # ------------------------------------------------------------------

    def api_error_type(self) -> type:
        """Return ``openai.OpenAIError`` — same SDK, same exceptions."""
        import openai

        return openai.OpenAIError

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_model_names(base_url: str) -> list[str]:
        """Fetch pulled model names from ``GET {base_url}/api/tags``.

        Returns an empty list on any error (Ollama may not be running yet).
        """
        try:
            import httpx

            resp = httpx.get(f"{base_url}/api/tags", timeout=4.0)
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", []) if "name" in m]
        except Exception as exc:
            logger.debug("OllamaProvider: could not fetch model list: %s", exc)
            return []

    def _warn_non_tool_models(self, settings: Any) -> None:
        """Emit a warning for each configured model that is unlikely to support tools."""
        model_fields = [
            "planning_model",
            "plan_edit_model",
            "part_finder_model",
            "part_selection_model",
            "documentation_model",
            "code_generation_model",
            "code_validation_model",
            "code_correction_model",
            "erc_handling_model",
            "runtime_correction_model",
        ]
        seen: set[str] = set()
        for field in model_fields:
            model = getattr(settings, field, None)
            if not model or model in seen:
                continue
            seen.add(model)
            base = _model_base(model)
            if base not in _TOOL_CAPABLE_PREFIXES:
                warnings.warn(
                    f"OllamaProvider: model '{model}' is not in the known "
                    f"tool-capable list.  Tool/function calling may not work.  "
                    f"Consider using a model like qwen2.5-coder:32b or llama3.2.",
                    stacklevel=3,
                )
            elif self._available_models and model not in self._available_models:
                warnings.warn(
                    f"OllamaProvider: model '{model}' is not in the list of "
                    f"pulled Ollama models.  Run: ollama pull {model}",
                    stacklevel=3,
                )


__all__ = ["OllamaProvider"]
