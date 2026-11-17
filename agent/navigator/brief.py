"""Brief assembly: the Tenant Stabilization Brief JSON (docs/ARCHITECTURE.md#brief-json).

Owner: Karthik.

The model never types evidence rows itself. It names request_ids and statute ids, and
submit_brief copies the real rows from what the tools returned this session (kept in
session state by `remember_tool_results`). Citing an excluded decoy or an ID no tool
returned is rejected, so the brief can't contain a hallucinated or decoy record.

API contract (April): when a `submit_brief` or `add_equity_note` function response has
status "ok", send `{"type": "brief", "brief": response["brief"]}` to the UI.
"""

from typing import Any, Optional

from google.adk.tools import ToolContext

# Session state keys
SEEN_COMPLAINTS = "seen_complaints"
EXCLUDED_COMPLAINTS = "excluded_complaints"
SEEN_STATUTES = "seen_statutes"
LAST = "last_"  # last_match_fund, last_tract_context, last_equity_audit
BRIEF = "brief"
AWAITING_ANSWER = "awaiting_answer_in_invocation"  # set when a question must go back to the paralegal
# Multi-agent mode: raw results of tools a specialist ran during its latest call, as
# [{"tool", "args", "response"}]. Specialists' events aren't streamed, so the API reads this
# from the coordinator's function_response event (event.actions.state_delta) to fill the panels.
SPECIALIST_TRACE = "specialist_trace"
ROOT_AGENT_NAME = "navigator"

BASE_CANNOT_PROVE = [
    "311 records show conditions on the block, not inside this tenant's unit",
    "Eviction filing counts are modeled neighborhood baselines, not court dockets",
]


def remember_tool_results(tool, args: dict, tool_context: ToolContext, tool_response: Any):
    """after_tool_callback: keep each tool's real output in session state for submit_brief."""
    if not isinstance(tool_response, dict) or "error" in tool_response:
        return None
    state = tool_context.state
    if tool_context.agent_name != ROOT_AGENT_NAME:
        state[SPECIALIST_TRACE] = list(state.get(SPECIALIST_TRACE) or []) + [
            {"tool": tool.name, "args": dict(args or {}), "response": tool_response}]
    if tool.name == "resolve_date" and (tool_response.get("ambiguous") or tool_response.get("in_past")):
        # The paralegal must answer before a brief is written; checked in submit_brief.
        state[AWAITING_ANSWER] = tool_context.invocation_id
    if tool.name == "semantic_search":
        corpus = tool_response.get("corpus")
        if corpus == "complaints":
            seen = dict(state.get(SEEN_COMPLAINTS, {}))
            seen.update({m["request_id"]: m for m in tool_response.get("matches", [])})
            state[SEEN_COMPLAINTS] = seen
            excluded = dict(state.get(EXCLUDED_COMPLAINTS, {}))
            excluded.update({e["request_id"]: e for e in tool_response.get("excluded", [])})
            state[EXCLUDED_COMPLAINTS] = excluded
        elif corpus == "statutes":
            seen = dict(state.get(SEEN_STATUTES, {}))
            seen.update({s["statute_section_id"]: s for s in tool_response.get("matches", [])})
            state[SEEN_STATUTES] = seen
    elif tool.name in ("match_fund", "tract_context", "equity_audit"):
        state[LAST + tool.name] = tool_response
    return None


def submit_brief(
    block_address: str,
    hazards: list[str],
    evidence_request_ids: list[str],
    statute_ids: list[str],
    memo_markdown: str,
    tool_context: ToolContext,
    hearing_date: Optional[str] = None,
    household_size: Optional[int] = None,
    income_pct_ami: Optional[float] = None,
    extra_cannot_prove: Optional[list[str]] = None,
) -> dict:
    """Assemble and publish the Tenant Stabilization Brief shown to the paralegal.

    Call after semantic_search (complaints and statutes) and match_fund, and tract_context
    if a tract is known. Evidence and statutes are copied from those tool results by ID.

    Args:
        block_address: Tenant's block, e.g. "400 Block Eddy St, San Francisco, CA".
        hazards: Reported conditions, e.g. ["no heat", "mold"].
        evidence_request_ids: request_ids from semantic_search `matches` to cite. Never excluded ones.
        statute_ids: statute_section_ids from semantic_search(corpus="statutes").
        memo_markdown: Legal-aid intake memo in Markdown (facts, evidence, law, funds, next steps, caveats).
        hearing_date: Hearing date as YYYY-MM-DD, if known.
        household_size: Number of people in the household, if known.
        income_pct_ami: Household income as % of Area Median Income, if known.
        extra_cannot_prove: Case-specific limits of the evidence, beyond the standard caveats.
    """
    state = tool_context.state
    if state.get(AWAITING_ANSWER) == tool_context.invocation_id:
        return {"status": "error", "errors": [
            "The hearing date is ambiguous or in the past. Ask the paralegal to confirm it and "
            "end your turn. Do not submit the brief until they answer."]}
    seen = state.get(SEEN_COMPLAINTS, {})
    excluded = state.get(EXCLUDED_COMPLAINTS, {})
    statutes_seen = state.get(SEEN_STATUTES, {})

    errors = []
    for rid in evidence_request_ids:
        if rid in excluded:
            errors.append(f"{rid} is excluded ({excluded[rid]['reason']}). Remove it from evidence.")
        elif rid not in seen:
            errors.append(f"{rid} was not returned by semantic_search. Cite only returned matches.")
    for sid in statute_ids:
        if sid not in statutes_seen:
            errors.append(f"Statute {sid} was not returned by semantic_search(corpus='statutes').")
    if errors:
        return {"status": "error", "errors": errors}

    evidence = []
    for rid in evidence_request_ids:
        r = seen[rid]
        evidence.append({k: r.get(k) for k in (
            "request_id", "block_address", "census_tract_geoid", "raw_complaint_type",
            "inspection_status", "created_date", "similarity", "on_tenant_block", "narrative",
            "data_provenance")})

    statutes = [{
        "statute_section_id": sid,
        "code_citation": statutes_seen[sid].get("code_citation"),
        "ordinance_title": statutes_seen[sid].get("ordinance_title"),
        "protection": statutes_seen[sid].get("text"),
    } for sid in statute_ids]

    fund_result = state.get(LAST + "match_fund") or {}
    tract = state.get(LAST + "tract_context")
    tract_out = None
    if tract:
        tract_out = {k: tract.get(k) for k in (
            "census_tract_geoid", "severe_rent_burden_pct",
            "metro_severe_rent_burden_pct", "annual_filings_modeled")}

    stubs = [name for name in ("match_fund", "tract_context")
             if (state.get(LAST + name) or {}).get("stub")]

    brief = {
        "case": {
            "block_address": block_address,
            "hazards": hazards,
            "hearing_date": hearing_date,
            "household_size": household_size,
            "income_pct_ami": income_pct_ami,
        },
        "evidence": evidence,
        "excluded": sorted(excluded.values(), key=lambda e: -e.get("similarity", 0)),
        "statutes": statutes,
        "funds": fund_result.get("funds", []),
        "tract_context": tract_out,
        "equity_note": (state.get(BRIEF) or {}).get("equity_note"),
        "cannot_prove": BASE_CANNOT_PROVE + list(extra_cannot_prove or []),
        "memo_markdown": memo_markdown,
        "stub_tools": stubs,  # non-empty means some sections are placeholder data
    }
    state[BRIEF] = brief
    return {"status": "ok", "brief": brief}


def add_equity_note(equity_note: str, tool_context: ToolContext) -> dict:
    """Attach the post-output equity audit note to the already-submitted brief.

    Args:
        equity_note: One or two sentences on what the equity audit showed and any outreach change.
    """
    brief = tool_context.state.get(BRIEF)
    if not brief:
        return {"status": "error", "errors": ["Call submit_brief first."]}
    brief = {**brief, "equity_note": equity_note}
    tool_context.state[BRIEF] = brief
    return {"status": "ok", "brief": brief}
