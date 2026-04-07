"""Anthropic provider — concrete ``LLMProvider`` backed by the Anthropic API.

Install the extra before use::

    pip install circuitron[anthropic]

Set ``CIRCUITRON_PROVIDER=anthropic`` and ``ANTHROPIC_API_KEY`` in the
environment, then the full pipeline uses Claude models instead of OpenAI.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar, get_args, get_origin

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------

@dataclass
class AnthropicTool:
    """Wraps a plain callable with its Anthropic tool definition."""

    fn: Callable[..., Any]
    name: str
    description: str
    input_schema: dict[str, Any]

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass
class AnthropicAgentConfig:
    """Stores the full configuration for one Anthropic-backed agent."""

    name: str
    instructions: str
    tools: list[AnthropicTool]
    output_type: type[Any]
    model: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class _RawResponse:
    """Thin wrapper so ``record_from_run_result`` can read usage fields."""

    model: str
    usage: Any  # anthropic.types.Usage


class _AnthropicGuardrailTripwire(Exception):
    """Raised if an Anthropic guardrail rejects a query (placeholder)."""


@dataclass
class AnthropicRunResult:
    """Equivalent of ``agents.RunResult`` for the Anthropic provider."""

    output: Any
    raw_responses: list[_RawResponse]

    @property
    def final_output(self) -> Any:
        """Alias for ``output``; mirrors the OpenAI SDK ``RunResult`` API."""
        return self.output


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class AnthropicProvider:
    """``LLMProvider`` backed by the Anthropic Messages API.

    Implements a full agentic loop: tool calling is handled manually until
    the model emits a ``result`` tool call carrying the structured output.
    """

    def __init__(self) -> None:
        try:
            import anthropic as _anthropic
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "The 'anthropic' package is required for AnthropicProvider. "
                "Install it with: pip install circuitron[anthropic]"
            ) from exc
        self._client = _anthropic.AsyncAnthropic()
        self._anthropic = _anthropic

    # ------------------------------------------------------------------
    # LLMProvider protocol
    # ------------------------------------------------------------------

    def create_agent(
        self,
        name: str,
        instructions: str,
        tools: list[Any],
        output_type: type[Any],
        model: str,
        **kwargs: Any,
    ) -> AnthropicAgentConfig:
        """Build an :class:`AnthropicAgentConfig` from provider-agnostic args."""
        wrapped = [
            t if isinstance(t, AnthropicTool) else self._make_tool(t)
            for t in (tools or [])
        ]
        return AnthropicAgentConfig(
            name=name,
            instructions=instructions,
            tools=wrapped,
            output_type=output_type,
            model=model,
            extra=kwargs,
        )

    async def run_agent(
        self,
        agent: Any,
        input_data: Any,
        max_turns: int,
        **kwargs: Any,
    ) -> AnthropicRunResult:
        """Run the agentic loop until structured output is produced.

        Uses a special ``result`` tool to elicit structured output from the
        model.  Regular tool calls are executed and fed back as tool results.
        """
        cfg: AnthropicAgentConfig = agent
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": str(input_data)}
        ]
        raw_responses: list[_RawResponse] = []

        output_tool = self._build_output_tool(cfg.output_type)
        api_tools = [t.to_api_dict() for t in cfg.tools] + [output_tool]
        tool_map = {t.name: t for t in cfg.tools}

        for turn in range(max_turns):
            # Force the result tool on the last available turn
            tool_choice: dict[str, Any] = (
                {"type": "tool", "name": "result"}
                if turn == max_turns - 1
                else {"type": "any"}
            )

            response = await self._client.messages.create(
                model=cfg.model,
                system=cfg.instructions,
                messages=messages,
                tools=api_tools,
                tool_choice=tool_choice,
                max_tokens=4096,
            )
            raw_responses.append(_RawResponse(model=cfg.model, usage=response.usage))

            # Scan content blocks
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            result_block = next((b for b in tool_uses if b.name == "result"), None)

            if result_block is not None:
                output = cfg.output_type.model_validate(result_block.input)
                return AnthropicRunResult(output=output, raw_responses=raw_responses)

            if not tool_uses:
                # No tools called and no result — parse last text block as fallback
                text_blocks = [b for b in response.content if b.type == "text"]
                if text_blocks:
                    raw_json = _extract_json(text_blocks[-1].text)
                    output = cfg.output_type.model_validate_json(raw_json)
                    return AnthropicRunResult(output=output, raw_responses=raw_responses)
                break

            # Execute tool calls and collect results
            messages.append({"role": "assistant", "content": response.content})
            tool_results: list[dict[str, Any]] = []
            for block in tool_uses:
                if block.name == "result":
                    continue
                tool_obj = tool_map.get(block.name)
                if tool_obj is None:
                    content = json.dumps({"error": f"Unknown tool: {block.name}"})
                else:
                    content = await _call_tool(tool_obj.fn, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        raise RuntimeError(
            f"AnthropicProvider: agent '{cfg.name}' did not produce "
            f"structured output within {max_turns} turns."
        )

    def extract_output(self, result: Any, output_type: type[T]) -> T:
        """Return the already-validated output stored in the run result."""
        return result.output  # type: ignore[no-any-return]

    def wrap_tool(self, fn: Any) -> AnthropicTool:
        """Convert a plain callable to an :class:`AnthropicTool`.

        The tool definition (name, description, input schema) is derived from
        the function signature and docstring at wrap time.
        """
        return self._make_tool(fn)

    def api_error_type(self) -> type:
        """Return :class:`anthropic.APIError` for use in ``except`` clauses."""
        return self._anthropic.APIError  # type: ignore[no-any-return]

    def make_mcp_server(self, url: str, timeout: float) -> Any:
        """Return an Anthropic-compatible MCP server stub.

        Full MCP integration for Anthropic requires ``anthropic>=0.49.0`` and
        is wired differently from the OpenAI Agents SDK.  This stub is a
        placeholder; pass MCP server objects via ``extra["mcp_servers"]`` in
        ``create_agent`` when needed.
        """
        raise NotImplementedError(
            "Anthropic MCP integration is handled differently from the OpenAI "
            "Agents SDK.  Use the anthropic SDK's built-in MCP support directly."
        )

    def make_guardrail(self, check_fn: Any) -> Any:
        """Return ``check_fn`` unchanged.

        Anthropic guardrail enforcement is not yet implemented; the returned
        function is accepted by ``create_agent`` via ``input_guardrails`` but
        is not called during ``run_agent``.
        """
        return check_fn

    def guardrail_tripwire_type(self) -> type:
        """Return a sentinel exception that this provider never raises.

        Because Anthropic guardrails are not yet enforced, this exception will
        never be caught in practice.
        """
        return _AnthropicGuardrailTripwire

    def display_run_items(self, result: Any) -> None:
        """Print a short summary of the Anthropic run result."""
        output = getattr(result, "output", None)
        if output is not None:
            print(f"[anthropic] OUTPUT: {output}")

    def extract_reasoning(self, result: Any) -> str:
        """Return a placeholder — Anthropic responses have no reasoning summary field."""
        return "(no summary returned)"

    @staticmethod
    def configure_tracing() -> None:
        """Instrument the Anthropic client with Logfire if available."""
        try:
            import anthropic as _anthropic
            import logfire

            logfire.instrument_anthropic(_anthropic)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_tool(self, fn: Callable[..., Any]) -> AnthropicTool:
        """Build an :class:`AnthropicTool` from a plain callable."""
        name = fn.__name__
        doc = inspect.getdoc(fn) or ""
        description = doc.split("\n")[0] or name
        input_schema = _fn_to_input_schema(fn)
        return AnthropicTool(fn=fn, name=name, description=description, input_schema=input_schema)

    @staticmethod
    def _build_output_tool(output_type: type[Any]) -> dict[str, Any]:
        """Create the special ``result`` tool that forces structured output."""
        schema = output_type.model_json_schema()
        # Remove $defs / $schema meta-keys that confuse some models
        schema.pop("$schema", None)
        return {
            "name": "result",
            "description": (
                f"Return the final structured {output_type.__name__} result. "
                "Call this tool exactly once when you have all the information needed."
            ),
            "input_schema": schema,
        }


# ---------------------------------------------------------------------------
# Schema generation helpers
# ---------------------------------------------------------------------------

def _fn_to_input_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """Build an Anthropic input_schema dict from a function's type hints."""
    sig = inspect.signature(fn)
    hints = fn.__annotations__ if hasattr(fn, "__annotations__") else {}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "ctx", "return"):
            continue
        annotation = hints.get(param_name, inspect.Parameter.empty)
        prop = _annotation_to_schema(annotation)
        properties[param_name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    return {"type": "object", "properties": properties, "required": required}


def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
    """Convert a Python type annotation to a JSON Schema dict."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}

    origin = get_origin(annotation)
    args = get_args(annotation)

    # Optional[X] / X | None
    if origin is type(None):
        return {"type": "null"}
    if origin is not None and hasattr(origin, "__name__") is False:
        # Union / Optional
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _annotation_to_schema(non_none[0])

    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}

    if origin is list:
        item_schema = _annotation_to_schema(args[0]) if args else {}
        return {"type": "array", "items": item_schema}
    if origin is dict:
        return {"type": "object"}

    # Pydantic model
    if hasattr(annotation, "model_json_schema"):
        return annotation.model_json_schema()

    return {"type": "string"}  # safe fallback


# ---------------------------------------------------------------------------
# Tool execution helper
# ---------------------------------------------------------------------------

async def _call_tool(fn: Callable[..., Any], args: dict[str, Any]) -> str:
    """Call a tool function (sync or async) and return a JSON string result."""
    try:
        result = fn(**args)
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, str):
            return result
        return json.dumps(result, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _extract_json(text: str) -> str:
    """Extract the first JSON object or array from a text string."""
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if match:
        return match.group(1)
    return text


__all__ = ["AnthropicProvider", "AnthropicAgentConfig", "AnthropicRunResult"]
