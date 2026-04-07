"""OpenAI Agents SDK provider — the single file that imports from ``agents`` and ``openai``.

All other Circuitron modules obtain SDK types and behaviour through this module
rather than importing from ``agents.*`` or ``openai`` directly.
"""

from __future__ import annotations

import importlib
from typing import Any, TypeVar

import openai
from agents import Agent, GuardrailFunctionOutput, Runner, function_tool, input_guardrail
from agents.exceptions import InputGuardrailTripwireTriggered
from agents.items import MessageOutputItem, ReasoningItem, ToolCallOutputItem
from agents.mcp import MCPServer, MCPServerSse
from agents.model_settings import ModelSettings
from agents.result import RunResult
from agents.tool import Tool

T = TypeVar("T")

# Convenience alias so callers can write ``except APIError`` without an openai import.
APIError = openai.OpenAIError


class OpenAIAgentsProvider:
    """Concrete ``LLMProvider`` backed by the OpenAI Agents SDK.

    Satisfies the ``LLMProvider`` protocol defined in ``circuitron.provider``.
    Instantiate once at module level and pass or import as needed.
    """

    # ------------------------------------------------------------------
    # LLMProvider protocol methods
    # ------------------------------------------------------------------

    def create_agent(
        self,
        name: str,
        instructions: str,
        tools: list[Any],
        output_type: type[Any],
        model: str,
        **kwargs: Any,
    ) -> Agent:
        """Create an :class:`~agents.Agent` from provider-agnostic arguments.

        Converts a :class:`~circuitron.provider.ModelConfig` passed as
        ``model_settings`` into the SDK's :class:`~agents.ModelSettings`.
        All other kwargs are forwarded directly to the SDK constructor.
        """
        mc = kwargs.pop("model_settings", None)
        if mc is not None:
            from ..provider import ModelConfig
            if isinstance(mc, ModelConfig):
                kwargs["model_settings"] = ModelSettings(
                    tool_choice=mc.tool_choice,
                    parallel_tool_calls=mc.parallel_tool_calls,
                )
            else:
                # Already a ModelSettings or similar — pass through unchanged.
                kwargs["model_settings"] = mc
        return Agent(
            name=name,
            instructions=instructions,
            tools=tools,
            output_type=output_type,
            model=model,
            **kwargs,
        )

    async def run_agent(
        self,
        agent: Any,
        input_data: Any,
        max_turns: int,
        **kwargs: Any,
    ) -> RunResult:
        """Run *agent* via :class:`~agents.Runner` and return the raw result.

        Extra kwargs (e.g. ``context=``) are forwarded to :meth:`Runner.run`.
        """
        return await Runner.run(agent, input_data, max_turns=max_turns, **kwargs)

    def extract_output(self, result: Any, output_type: type[T]) -> T:
        """Extract typed output from a run result.

        Replaces ``result.final_output_as(output_type)`` at call sites.
        """
        return result.final_output_as(output_type)

    def wrap_tool(self, fn: Any) -> Any:
        """Wrap a plain callable as an SDK :class:`~agents.tool.FunctionTool`.

        Replaces ``@function_tool`` at call sites.
        """
        return function_tool(fn)

    def api_error_type(self) -> type:
        """Return :class:`openai.OpenAIError` for use in ``except`` clauses."""
        return openai.OpenAIError

    def make_mcp_server(self, url: str, timeout: float) -> MCPServerSse:
        """Create an :class:`~agents.mcp.MCPServerSse` for the ``skidl_docs`` server."""
        return MCPServerSse(
            name="skidl_docs",
            params={
                "url": url,
                "timeout": timeout,
                "sse_read_timeout": timeout * 2,
            },
            cache_tools_list=True,
            client_session_timeout_seconds=timeout,
        )

    def make_guardrail(self, check_fn: Any) -> Any:
        """Wrap ``check_fn`` with ``@input_guardrail`` for the OpenAI Agents SDK.

        ``check_fn`` is ``async (input_data) -> bool`` where ``True`` means
        the query is allowed through.  The wrapper converts the bool into a
        :class:`~agents.GuardrailFunctionOutput` and trips the wire when
        ``False``.
        """
        @input_guardrail
        async def _guardrail(ctx: Any, agent: Any, input_data: Any) -> GuardrailFunctionOutput:
            is_relevant = await check_fn(input_data)
            return GuardrailFunctionOutput(
                output_info=None,
                tripwire_triggered=not is_relevant,
            )
        return _guardrail

    def guardrail_tripwire_type(self) -> type:
        """Return :class:`~agents.exceptions.InputGuardrailTripwireTriggered`."""
        return InputGuardrailTripwireTriggered

    def display_run_items(self, result: Any) -> None:
        """Print all new items from a run result (dev-mode debugging)."""
        for item in result.new_items:
            agent_name = getattr(item.agent, "name", "agent")
            if isinstance(item, MessageOutputItem):
                parts = []
                for part in item.raw_item.content:
                    text = getattr(part, "text", None)
                    if text:
                        parts.append(text)
                print(f"[{agent_name}] MESSAGE: {''.join(parts)}")
            elif isinstance(item, ToolCallOutputItem):
                print(f"[{agent_name}] TOOL OUTPUT: {item.output}")
            else:
                print(f"[{agent_name}] {item.type}")

    def extract_reasoning(self, result: Any) -> str:
        """Return the reasoning summary from an OpenAI Agents SDK run result."""
        texts = []
        for item in getattr(result, "new_items", []):
            if isinstance(item, ReasoningItem):
                for chunk in item.raw_item.summary:
                    if getattr(chunk, "type", None) == "summary_text":
                        texts.append(chunk.text)
        return "\n\n".join(texts).strip() or "(no summary returned)"

    # ------------------------------------------------------------------
    # Tracing / instrumentation
    # ------------------------------------------------------------------

    @staticmethod
    def configure_tracing() -> None:
        """Call ``logfire.instrument_openai_agents()``.

        Called from :func:`~circuitron.config.setup_environment` so that
        all SDK traces are captured without importing logfire elsewhere.
        """
        logfire = importlib.import_module("logfire")
        logfire.instrument_openai_agents()


# ---------------------------------------------------------------------------
# Re-exported SDK types
# ---------------------------------------------------------------------------
# Other Circuitron modules import these from here rather than from agents.*
# directly, keeping all SDK coupling confined to this single file.

__all__ = [
    "OpenAIAgentsProvider",
    # SDK types re-exported for use in type annotations
    "Agent",
    "Tool",
    "ModelSettings",
    "MCPServer",
    "MCPServerSse",
    "RunResult",
    "MessageOutputItem",
    "ToolCallOutputItem",
    "InputGuardrailTripwireTriggered",
    "GuardrailFunctionOutput",
    "input_guardrail",
    "APIError",
]
