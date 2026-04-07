"""Agent definitions and configurations for the Circuitron system.

This module contains all specialized agents used in the PCB design
pipeline. The agents operate in a deterministic sequential flow where
each agent performs a specific task and passes its output to the next
agent via explicit orchestration in the pipeline module.

The system uses a single MCP server connection shared across all agents
that require documentation and validation capabilities.
"""

from typing import Any

from .providers import get_provider
from .provider import AgentHandle, ModelConfig

from .config import settings
from .prompts import (
    PLAN_PROMPT,
    PLAN_EDIT_PROMPT,
    PARTFINDER_PROMPT,
    PARTFINDER_PROMPT_NO_FOOTPRINT,
    PART_SELECTION_PROMPT,
    PART_SELECTION_PROMPT_NO_FOOTPRINT,
    DOC_AGENT_PROMPT,
    CODE_GENERATION_PROMPT,
    CODE_GENERATION_PROMPT_NO_FOOTPRINT,
    CODE_VALIDATION_PROMPT,
    CODE_CORRECTION_PROMPT,
    ERC_HANDLING_PROMPT,
    RUNTIME_ERROR_CORRECTION_PROMPT,
)
from .models import (
    PlanOutput,
    PlanEditorOutput,
    PartFinderOutput,
    PartSelectionOutput,
    DocumentationOutput,
    CodeGenerationOutput,
    CodeValidationOutput,
    CodeCorrectionOutput,
    ERCHandlingOutput,
    RuntimeErrorCorrectionOutput,
)
from .tools import (
    execute_calculation,
    search_kicad_libraries,
    search_kicad_footprints,
    extract_pin_details,
    run_erc,
    run_runtime_check,
    get_kg_usage_guide,
)

_provider = get_provider(settings)

# Wrap plain callables as SDK tools via the provider.
_execute_calculation = _provider.wrap_tool(execute_calculation)
_search_kicad_libraries = _provider.wrap_tool(search_kicad_libraries)
_search_kicad_footprints = _provider.wrap_tool(search_kicad_footprints)
_extract_pin_details = _provider.wrap_tool(extract_pin_details)
_run_erc = _provider.wrap_tool(run_erc)
_run_runtime_check = _provider.wrap_tool(run_runtime_check)
_get_kg_usage_guide = _provider.wrap_tool(get_kg_usage_guide)
from .mcp_manager import mcp_manager
from .guardrails import pcb_query_guardrail


def _tool_choice_for_mcp(model: str) -> str:
    """Return appropriate tool_choice for MCP tools based on the model.
    Only return 'auto' if the model is exactly 'o4-mini', else 'required'."""
    return "auto" if model == "o4-mini" else "required"


def create_planning_agent() -> AgentHandle:
    """Create and configure the Planning Agent."""
    model_settings = ModelConfig(tool_choice="required")

    tools: list[Any] =[_execute_calculation]

    return _provider.create_agent(
        name="Circuitron-Planner",
        instructions=PLAN_PROMPT,
        model=settings.planning_model,
        output_type=PlanOutput,
        tools=tools,
        input_guardrails=[pcb_query_guardrail],
        model_settings=model_settings,
    )


def create_plan_edit_agent() -> AgentHandle:
    """Create and configure the Plan Edit Agent."""
    model_settings = ModelConfig(tool_choice="required")

    tools: list[Any] =[_execute_calculation]

    return _provider.create_agent(
        name="Circuitron-PlanEditor",
        instructions=PLAN_EDIT_PROMPT,
        model=settings.plan_edit_model,
        output_type=PlanEditorOutput,
        tools=tools,
        model_settings=model_settings,
    )


def create_partfinder_agent(footprint_search_enabled: bool = True) -> AgentHandle:
    """Create and configure the PartFinder Agent.

    Args:
        footprint_search_enabled: Include footprint search tool when ``True``.

    Returns:
        Configured :class:`~agents.Agent` instance.
    """
    # KiCad tools operate inside a single Docker container; avoid parallel tool calls
    model_settings = ModelConfig(tool_choice="required", parallel_tool_calls=False)

    tools: list[Any] =[_search_kicad_libraries]
    prompt = PARTFINDER_PROMPT
    if footprint_search_enabled:
        tools.append(_search_kicad_footprints)
    else:
        prompt = PARTFINDER_PROMPT_NO_FOOTPRINT

    return _provider.create_agent(
        name="Circuitron-PartFinder",
        instructions=prompt,
        model=settings.part_finder_model,
        output_type=PartFinderOutput,
        tools=tools,
        model_settings=model_settings,
    )


def create_partselection_agent() -> AgentHandle:
    """Create and configure the Part Selection Agent."""
    # Serializes calls to KiCad-backed tools to prevent container races
    model_settings = ModelConfig(tool_choice="required", parallel_tool_calls=False)

    tools: list[Any] =[_extract_pin_details]

    prompt = (
        PART_SELECTION_PROMPT
        if settings.footprint_search_enabled
        else PART_SELECTION_PROMPT_NO_FOOTPRINT
    )
    return _provider.create_agent(
        name="Circuitron-PartSelector",
        instructions=prompt,
        model=settings.part_selection_model,
        output_type=PartSelectionOutput,
        tools=tools,
        model_settings=model_settings,
    )


def create_documentation_agent() -> AgentHandle:
    """Create and configure the Documentation Agent."""
    model_settings = ModelConfig(
        tool_choice=_tool_choice_for_mcp(settings.documentation_model)
    )

    return _provider.create_agent(
        name="Circuitron-DocSeeker",
        instructions=DOC_AGENT_PROMPT,
        model=settings.documentation_model,
        output_type=DocumentationOutput,
        tools=[],
        mcp_servers=[mcp_manager.get_server()],
        model_settings=model_settings,
    )


def create_code_generation_agent() -> AgentHandle:
    """Create and configure the Code Generation Agent."""
    model_settings = ModelConfig(
        tool_choice=_tool_choice_for_mcp(settings.code_generation_model)
    )

    prompt = (
        CODE_GENERATION_PROMPT
        if settings.footprint_search_enabled
        else CODE_GENERATION_PROMPT_NO_FOOTPRINT
    )
    return _provider.create_agent(
        name="Circuitron-Coder",
        instructions=prompt,
        model=settings.code_generation_model,
        output_type=CodeGenerationOutput,
        tools=[],
        mcp_servers=[mcp_manager.get_server()],
        model_settings=model_settings,
    )


def create_code_validation_agent() -> AgentHandle:
    """Create and configure the Code Validation Agent."""
    model_settings = ModelConfig(
        tool_choice=_tool_choice_for_mcp(settings.code_validation_model)
    )

    tools: list[Any] =[_get_kg_usage_guide]

    return _provider.create_agent(
        name="Circuitron-Validator",
        instructions=CODE_VALIDATION_PROMPT,
        model=settings.code_validation_model,
        output_type=CodeValidationOutput,
        tools=tools,
        mcp_servers=[mcp_manager.get_server()],
        model_settings=model_settings,
    )


def create_code_correction_agent() -> AgentHandle:
    """Create and configure the Code Correction Agent."""
    model_settings = ModelConfig(
        tool_choice=_tool_choice_for_mcp(settings.code_correction_model)
    )

    tools: list[Any] =[_get_kg_usage_guide]

    return _provider.create_agent(
        name="Circuitron-Corrector",
        instructions=CODE_CORRECTION_PROMPT,
        model=settings.code_correction_model,
        output_type=CodeCorrectionOutput,
        tools=tools,
        mcp_servers=[mcp_manager.get_server()],
        model_settings=model_settings,
    )


def create_runtime_error_correction_agent() -> AgentHandle:
    """Create and configure the Runtime Error Correction Agent."""

    # Runtime checker uses the KiCad Docker session; keep tool calls sequential
    model_settings = ModelConfig(
        tool_choice=_tool_choice_for_mcp(settings.runtime_correction_model),
        parallel_tool_calls=False,
    )

    tools: list[Any] =[_get_kg_usage_guide, _run_runtime_check]

    return _provider.create_agent(
        name="Circuitron-RuntimeCorrector",
        instructions=RUNTIME_ERROR_CORRECTION_PROMPT,
        model=settings.runtime_correction_model,
        output_type=RuntimeErrorCorrectionOutput,
        tools=tools,
        mcp_servers=[mcp_manager.get_server()],
        model_settings=model_settings,
    )


def create_erc_handling_agent() -> AgentHandle:
    """Create and configure the ERC Handling Agent."""
    # ERC tool runs in the KiCad Docker session; avoid parallel tool calls
    model_settings = ModelConfig(
        tool_choice=_tool_choice_for_mcp(settings.erc_handling_model),
        parallel_tool_calls=False,
    )

    tools: list[Any] =[_run_erc]

    return _provider.create_agent(
        name="Circuitron-ERCHandler",
        instructions=ERC_HANDLING_PROMPT,
        model=settings.erc_handling_model,
        output_type=ERCHandlingOutput,
        tools=tools,
        mcp_servers=[mcp_manager.get_server()],
        model_settings=model_settings,
    )


def get_planning_agent() -> AgentHandle:
    """Return a new instance of the Planning Agent."""

    return create_planning_agent()


def get_plan_edit_agent() -> AgentHandle:
    """Return a new instance of the Plan Edit Agent."""

    return create_plan_edit_agent()


def get_partfinder_agent() -> AgentHandle:
    """Return a new instance of the PartFinder Agent."""

    return create_partfinder_agent(settings.footprint_search_enabled)


def get_partselection_agent() -> AgentHandle:
    """Return a new instance of the Part Selection Agent."""

    return create_partselection_agent()


def get_documentation_agent() -> AgentHandle:
    """Return a new instance of the Documentation Agent."""

    return create_documentation_agent()


def get_code_generation_agent() -> AgentHandle:
    """Return a new instance of the Code Generation Agent."""

    return create_code_generation_agent()


def get_code_validation_agent() -> AgentHandle:
    """Return a new instance of the Code Validation Agent."""

    return create_code_validation_agent()


def get_code_correction_agent() -> AgentHandle:
    """Return a new instance of the Code Correction Agent."""

    return create_code_correction_agent()


def get_runtime_error_correction_agent() -> AgentHandle:
    """Return a new instance of the Runtime Error Correction Agent."""

    return create_runtime_error_correction_agent()


def get_erc_handling_agent() -> AgentHandle:
    """Return a new instance of the ERC Handling Agent."""

    return create_erc_handling_agent()


__all__ = [
    "get_planning_agent",
    "get_plan_edit_agent",
    "get_partfinder_agent",
    "get_partselection_agent",
    "get_documentation_agent",
    "get_code_generation_agent",
    "get_code_validation_agent",
    "get_code_correction_agent",
    "get_runtime_error_correction_agent",
    "get_erc_handling_agent",
    "create_planning_agent",
    "create_plan_edit_agent",
    "create_partfinder_agent",
    "create_partselection_agent",
    "create_documentation_agent",
    "create_code_generation_agent",
    "create_code_validation_agent",
    "create_code_correction_agent",
    "create_runtime_error_correction_agent",
    "create_erc_handling_agent",
]
