"""Custom guardrails for Circuitron."""

from __future__ import annotations

from typing import Any

import asyncio
from pydantic import BaseModel
import httpx

from .providers import get_provider
from .ui.app import TerminalUI
from .network import is_connected
from .exceptions import PipelineError
from .config import settings
from .telemetry import record_from_run_result

_provider = get_provider(settings)


class PCBQueryOutput(BaseModel):
    """Output schema for the PCB relevance check."""

    is_relevant: bool
    reasoning: str


# Cheap model used to triage queries before running expensive agents
_QUERY_MODEL = "gpt-5-nano"

_pcb_query_agent = _provider.create_agent(
    name="PCB Query Check",
    instructions="Determine if the user's request is related to electrical or PCB design.",
    model=_QUERY_MODEL,
    output_type=PCBQueryOutput,
    tools=[],
)


async def _pcb_check(input_data: Any) -> bool:
    """Return ``True`` when ``input_data`` is a PCB-related query.

    Runs a cheap triage agent.  Returns ``True`` (allow through) on
    network errors to avoid blocking legitimate requests.
    """
    try:
        coro = _provider.run_agent(_pcb_query_agent, input_data, max_turns=1)
        result = await asyncio.wait_for(coro, timeout=settings.network_timeout)
    except asyncio.TimeoutError:
        if not is_connected(timeout=5.0):
            raise PipelineError(
                "Internet connection lost. Please check your connection and try again."
            )
        raise PipelineError(
            "Network operation timed out. Consider increasing CIRCUITRON_NETWORK_TIMEOUT."
        )
    except (httpx.HTTPError, _provider.api_error_type()) as exc:
        TerminalUI().display_error(f"Network error: {exc}")
        if not is_connected(timeout=5.0):
            raise PipelineError(
                "Internet connection lost. Please check your connection and try again."
            ) from exc
        raise PipelineError("Network connection issue") from exc

    try:
        record_from_run_result(result)
    except Exception:
        pass

    output = _provider.extract_output(result, PCBQueryOutput)
    return output.is_relevant


# Provider wraps _pcb_check into the SDK-specific guardrail format.
# For OpenAI this applies @input_guardrail + GuardrailFunctionOutput.
# For Anthropic it is stored but not enforced (pending implementation).
pcb_query_guardrail = _provider.make_guardrail(_pcb_check)


__all__ = ["pcb_query_guardrail"]
