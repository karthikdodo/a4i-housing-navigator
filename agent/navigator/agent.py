"""Root agent `navigator`. Owner: Karthik.

Run locally:  .venv/bin/adk web agent/ --reload_agents     (from the repo root)

==========================================================================================
FOR APRIL: how the WebSocket API (api/) runs this agent and streams it to the UI
==========================================================================================

Import (add `agent/` to PYTHONPATH):

    from navigator.agent import root_agent, TOOL_STATUS_TEXT

Rules:
  1. Create ONE Runner per server process and ONE ADK session per UI conversation
     (map the UI's session_id to it). The agent keeps evidence in session state between turns.
  2. Run with StreamingMode.SSE so the agent's text arrives in chunks.
  3. With SSE on, every function_call / function_response arrives TWICE (partial + final).
     Handle tool events only when `event.partial` is falsy, or the UI shows each step twice.
  4. A full case takes ~40 s over ~7 steps. Send a `status` event for every tool call so the
     UI never looks frozen.
  5. The brief is in the function_response of `submit_brief` or `add_equity_note` when its
     status is "ok". It's also in session state under "brief".

Example handler (tested; maps ADK events to the contract in docs/ARCHITECTURE.md):

    from google.adk.agents.run_config import RunConfig, StreamingMode
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=root_agent, app_name="navigator")   # once, at startup

    async def run_turn(ws, user_id: str, session_id: str, text: str):
        session = await runner.session_service.get_session(
            app_name="navigator", user_id=user_id, session_id=session_id)
        if session is None:
            await runner.session_service.create_session(
                app_name="navigator", user_id=user_id, session_id=session_id)

        message = types.Content(role="user", parts=[types.Part(text=text)])
        try:
            async for event in runner.run_async(
                user_id=user_id, session_id=session_id, new_message=message,
                run_config=RunConfig(streaming_mode=StreamingMode.SSE),
            ):
                for part in (event.content.parts if event.content else []) or []:
                    if part.text and not part.thought:
                        # partial chunk -> final False; the closing full text -> final True
                        await ws.send_json({"type": "message", "text": part.text,
                                            "final": not event.partial})
                    elif event.partial:
                        continue                                  # rule 3: skip duplicates
                    elif part.function_call:
                        name = part.function_call.name
                        await ws.send_json({"type": "status", "tool": name,
                                            "text": TOOL_STATUS_TEXT.get(name, "Working…")})
                    elif part.function_response:
                        resp = part.function_response.response or {}
                        if (part.function_response.name in ("submit_brief", "add_equity_note")
                                and resp.get("status") == "ok"):
                            await ws.send_json({"type": "brief", "brief": resp["brief"]})
        except Exception as e:
            await ws.send_json({"type": "error", "text": str(e)})

Note for the UI: when `final` is True, the text is the WHOLE reply again, not one more
chunk. Replace the streamed chunks with it; don't append it.

Deploy: needs everything in agent/requirements.txt (including `mcp`) and a service account
with BigQuery Job User, BigQuery Data Viewer, and Vertex AI User.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from google.adk.agents import Agent
from google.adk.agents.readonly_context import ReadonlyContext

from . import config
from .brief import add_equity_note, remember_tool_results, submit_brief
from .prompts import build_system_prompt
from .tools import equity_audit, match_fund, resolve_date, semantic_search, tract_context

# Status line the UI shows while each tool runs (api/ sends it as a `status` event).
TOOL_STATUS_TEXT = {
    "resolve_date": "Working out the date…",
    "semantic_search": "Searching 311 records, statutes, and funds…",
    "match_fund": "Checking emergency fund eligibility…",
    "tract_context": "Pulling neighborhood context…",
    "equity_audit": "Running the equity audit…",
    "submit_brief": "Writing the Stabilization Brief…",
    "add_equity_note": "Adding the equity note…",
    "list_table_ids": "Looking up BigQuery tables…",
    "get_table_info": "Reading a table schema…",
    "execute_sql_readonly": "Querying BigQuery…",
}

tools = [
    resolve_date,
    semantic_search,
    match_fund,
    tract_context,
    submit_brief,
    equity_audit,
    add_equity_note,
]
before_tool_callback = None
if config.ENABLE_BQ_MCP:
    from .bq_mcp import bigquery_mcp_toolset, block_audit_columns_before_brief

    tools.append(bigquery_mcp_toolset())
    before_tool_callback = block_audit_columns_before_brief

def instruction(_ctx: ReadonlyContext) -> str:
    """Rebuilt every turn so the model always knows today's date."""
    today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%A, %Y-%m-%d")
    return build_system_prompt(config.PROJECT, config.DATASET, today)


root_agent = Agent(
    name="navigator",
    model=config.MODEL,
    description="Builds a Tenant Stabilization Brief for a San Francisco eviction-defense intake.",
    instruction=instruction,
    tools=tools,
    before_tool_callback=before_tool_callback,
    after_tool_callback=remember_tool_results,
)
