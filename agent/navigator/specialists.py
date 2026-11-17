"""Specialist agents for multi-agent mode (config.MULTI_AGENT). Owner: Karthik / Sid.

    navigator (coordinator, root)  resolve_date, match_fund, submit_brief, add_equity_note
      ├─ evidence_researcher       semantic_search, locate_block, tract_context
      ├─ equity_auditor            equity_audit (post-brief only; code-enforced)
      └─ data_analyst              BigQuery MCP read-only tools (audit_* guard)

Each specialist is wrapped in an AgentTool, so the coordinator stays in charge of the
conversation and calls a specialist like a tool. Two ADK behaviours this design relies on:

  * A specialist's state writes (via `remember_tool_results`) are forwarded to the parent
    session, so `submit_brief` still validates every cited ID against real search rows.
  * A specialist's own events are NOT streamed to the runner. That is why `submit_brief`
    and `add_equity_note` stay on the coordinator: the API's `brief` event keeps working.
    The specialist's raw tool results ride along in state key `specialist_trace` on the
    coordinator's function_response event; api/runners.py replays them as `tool` events.
"""

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from . import config
from .brief import BRIEF, SPECIALIST_TRACE, remember_tool_results
from .prompts import EQUITY_PROMPT, EVIDENCE_PROMPT, _fill, build_data_analyst_prompt
from .tools import equity_audit, locate_block, semantic_search, tract_context

EVIDENCE_RESEARCHER = "evidence_researcher"
EQUITY_AUDITOR = "equity_auditor"
DATA_ANALYST = "data_analyst"


def evidence_researcher() -> Agent:
    return Agent(
        name=EVIDENCE_RESEARCHER,
        model=config.MODEL,
        description=(
            "Finds decoy-filtered 311 habitability evidence on and near the tenant's block, the "
            "applicable statutes, the tenant's census tract, and neighborhood context. Request: "
            "the tenant's block address, their problems, and a tract if the paralegal gave one."
        ),
        instruction=_fill(EVIDENCE_PROMPT),
        tools=[semantic_search, locate_block, tract_context],
        after_tool_callback=remember_tool_results,
    )


def equity_auditor() -> Agent:
    return Agent(
        name=EQUITY_AUDITOR,
        model=config.MODEL,
        description=(
            "Runs the post-brief equity audit for the tenant's census tract and returns a one or "
            "two sentence equity note. Only after submit_brief succeeded. Request: the tract GEOID."
        ),
        instruction=_fill(EQUITY_PROMPT),
        tools=[equity_audit],
        after_tool_callback=remember_tool_results,
    )


def data_analyst() -> Agent:
    from .bq_mcp import bigquery_mcp_toolset, block_audit_columns_before_brief

    return Agent(
        name=DATA_ANALYST,
        model=config.MODEL,
        description=(
            "Answers ad-hoc questions about the San Francisco housing tables with read-only "
            "BigQuery SQL. Not for finding brief evidence. Request: the question in plain words."
        ),
        instruction=build_data_analyst_prompt(config.PROJECT, config.DATASET),
        tools=[bigquery_mcp_toolset()],
        before_tool_callback=block_audit_columns_before_brief,
    )


def specialist_tools() -> list[AgentTool]:
    tools = [AgentTool(evidence_researcher()), AgentTool(equity_auditor())]
    if config.ENABLE_BQ_MCP:
        tools.append(AgentTool(data_analyst()))
    return tools


def coordinator_before_tool(tool, args: dict, tool_context):
    """Coordinator before_tool_callback.

    - The equity audit runs only after the brief exists.
    - Before each specialist call, reset SPECIALIST_TRACE so the coordinator's function_response
      event carries only that call's inner tool results (the API replays them to the panels).
    """
    if tool.name == EQUITY_AUDITOR and not tool_context.state.get(BRIEF):
        return {"error": "The equity audit runs only after submit_brief succeeds. Submit the brief first."}
    if tool.name in (EVIDENCE_RESEARCHER, EQUITY_AUDITOR, DATA_ANALYST):
        tool_context.state[SPECIALIST_TRACE] = []
    return None
