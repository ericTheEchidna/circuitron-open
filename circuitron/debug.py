"""Developer-facing debugging utilities."""

from __future__ import annotations

from typing import Any

import asyncio
import httpx

from .providers import get_provider
from .config import settings
from .telemetry import record_from_run_result
from .network import is_connected
from .exceptions import PipelineError

_provider = get_provider(settings)


def display_run_items(result: Any) -> None:
    """Print all new items from an agent run.

    Args:
        result: The run result from the active provider.
    """
    _provider.display_run_items(result)


async def run_agent(agent: Any, input_data: Any) -> Any:
    """Run an agent and display outputs when in dev mode.

    Args:
        agent: The agent to execute.
        input_data: The input to pass to the agent.

    Returns:
        The :class:`RunResult` from the agent run.
    """
    try:
        coro = _provider.run_agent(agent, input_data, max_turns=settings.max_turns)
        result = await asyncio.wait_for(coro, timeout=settings.network_timeout)
    except _provider.guardrail_tripwire_type():
        message = "Sorry, I can only assist with PCB design questions."
        print(message)
        raise PipelineError(message)
    except asyncio.TimeoutError:
        if not is_connected(timeout=5.0):
            raise PipelineError(
                "Internet connection lost. Please check your connection and try again."
            )
        raise PipelineError(
            "Network operation timed out. Consider increasing CIRCUITRON_NETWORK_TIMEOUT."
        )
    except (httpx.HTTPError, _provider.api_error_type()) as exc:
        print(f"Network error: {exc}")
        if not is_connected(timeout=5.0):
            raise PipelineError(
                "Internet connection lost. Please check your connection and try again."
            ) from exc
        raise PipelineError("Network connection issue") from exc

    # Aggregate token usage from raw responses as a fallback (no-op if none)
    try:
        record_from_run_result(result)
    except Exception:
        pass

    if settings.dev_mode:
        display_run_items(result)
    return result

__all__ = ["display_run_items", "run_agent"]
