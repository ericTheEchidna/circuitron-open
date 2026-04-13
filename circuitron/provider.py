"""Provider-agnostic protocol for LLM backends.

This module defines the ``LLMProvider`` and ``AgentHandle`` protocols plus
``ModelConfig``, a provider-neutral replacement for SDK-specific settings
objects such as ``ModelSettings`` from the OpenAI Agents SDK.

No SDK-specific imports appear here; concrete implementations live in
separate modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

T = TypeVar("T")


@dataclass
class ModelConfig:
    """Provider-agnostic model configuration.

    Replaces ``agents.model_settings.ModelSettings`` at call sites so that
    ``agents.py`` can remain free of SDK imports.  Each provider's
    ``create_agent`` implementation converts this to its own settings type.

    Attributes:
        tool_choice: How the model selects tools (``"auto"`` or
            ``"required"``).
        parallel_tool_calls: Allow the model to call multiple tools in a
            single turn when ``True``.
    """

    tool_choice: str = "auto"
    parallel_tool_calls: bool = True


class AgentHandle(Protocol):
    """Wraps a created agent object, regardless of which SDK produced it."""


class LLMProvider(Protocol):
    """Protocol that all LLM backend implementations must satisfy."""

    def create_agent(
        self,
        name: str,
        instructions: str,
        tools: list[Any] | None = None,
        output_type: type[Any] = object,
        model: str = "",
        **kwargs: Any,
    ) -> AgentHandle:
        """Create and return a provider-wrapped agent.

        Args:
            name: Display name for the agent.
            instructions: System prompt / instruction string.
            tools: List of wrapped tool callables.
            output_type: Pydantic model class for structured output.
            model: Model identifier string (e.g. ``"gpt-4o"``).
            **kwargs: Provider-specific extras (``mcp_servers``,
                ``model_settings`` as :class:`ModelConfig`,
                ``input_guardrails``, etc.).
        """
        ...

    async def run_agent(
        self,
        agent: AgentHandle,
        input_data: Any,
        max_turns: int,
        **kwargs: Any,
    ) -> Any:
        """Run an agent and return the provider-specific run result.

        Args:
            agent: An ``AgentHandle`` returned by ``create_agent``.
            input_data: The user message or structured input for this run.
            max_turns: Maximum number of agentic turns before halting.

        Returns:
            A provider-specific run result object.  Pass it to
            ``extract_output`` to retrieve the typed final value.
        """
        ...

    def extract_output(
        self,
        result: Any,
        output_type: type[T],
    ) -> T:
        """Extract the typed final output from a run result.

        Replaces ``result.final_output_as(output_type)`` from the
        OpenAI Agents SDK.

        Args:
            result: The run result returned by ``run_agent``.
            output_type: The expected output type; must match the
                ``output_type`` passed to ``create_agent``.

        Returns:
            The final structured output cast to ``output_type``.
        """
        ...

    def wrap_tool(self, fn: Any) -> Any:
        """Wrap a plain callable as a provider tool.

        Replaces the ``@function_tool`` decorator from the OpenAI Agents SDK.

        Args:
            fn: An async or sync callable with typed parameters and
                a docstring describing its behaviour to the model.

        Returns:
            A provider-specific tool object suitable for passing to
            ``create_agent``.
        """
        ...

    def api_error_type(self) -> type:
        """Return the provider's base API error class.

        Replaces ``openai.OpenAIError`` in ``except`` clauses so callers
        can catch the right exception without importing provider SDKs.

        Returns:
            The exception class that the provider raises on API failures.
        """
        ...

    def make_mcp_server(self, url: str, timeout: float) -> Any:
        """Create and return an MCP server instance for this provider.

        Args:
            url: Full SSE endpoint URL (e.g. ``http://localhost:8051/sse``).
            timeout: Network timeout in seconds.

        Returns:
            A provider-specific MCP server object.
        """
        ...

    def make_guardrail(self, check_fn: Any) -> Any:
        """Wrap a relevance-check function as a provider guardrail.

        ``check_fn`` must be an ``async`` callable that accepts ``input_data``
        and returns ``True`` when the query should be allowed through, or
        ``False`` to trip the wire.

        The returned object is suitable for use in the ``input_guardrails``
        kwarg of ``create_agent``.

        Args:
            check_fn: ``async (input_data: Any) -> bool``
        """
        ...

    def guardrail_tripwire_type(self) -> type:
        """Return the exception class raised when a guardrail trips.

        Replaces ``InputGuardrailTripwireTriggered`` in ``except`` clauses.

        Returns:
            The exception class raised by this provider when a guardrail
            rejects a query.
        """
        ...

    def display_run_items(self, result: Any) -> None:
        """Print all items from a run result for dev-mode debugging.

        Args:
            result: The run result returned by ``run_agent``.
        """
        ...

    def extract_reasoning(self, result: Any) -> str:
        """Extract any reasoning / chain-of-thought summary from a result.

        Args:
            result: The run result returned by ``run_agent``.

        Returns:
            A string summary, or ``"(no summary returned)"`` when unavailable.
        """
        ...

    def configure_tracing(self) -> None:
        """Instrument the provider's SDK with Logfire tracing.

        Called once during :func:`~circuitron.config.setup_environment`.
        Implementations should be no-ops if the required packages are absent.
        """
        ...


__all__ = ["AgentHandle", "LLMProvider", "ModelConfig"]
