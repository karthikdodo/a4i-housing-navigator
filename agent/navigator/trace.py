"""Live agent trace: every tool call by every agent (coordinator and sub-agents), as it happens.

Owner: Karthik.

Why: ADK runs a sub-agent (AgentTool) as a black box, so the runner only sees its result once
it finishes. These tool callbacks run inside every agent, including sub-agents, and report each
call's start and end to a sink the caller installs for the current turn:

    from navigator import trace
    token = trace.SINK.set(lambda ev: queue.put_nowait(ev))   # api/runners.py does this
    ...
    trace.SINK.reset(token)

With no sink installed (adk web, tests) the callbacks do nothing.

Event shape (JSON-safe):
    {"phase": "start"|"end", "id": <function_call_id>, "agent": "navigator"|"evidence_researcher"|...,
     "tool": <name>, "kind": "tool"|"agent", "args": {...short...}, "label": "...",
     "summary": "...", "ok": bool, "ms": int}
"""

import contextvars
import json
import time
from typing import Any, Callable, Optional

SINK: contextvars.ContextVar[Optional[Callable[[dict], None]]] = contextvars.ContextVar(
    "navigator_trace_sink", default=None
)

SUB_AGENTS = {"evidence_researcher", "equity_auditor", "data_analyst"}
_started: dict[str, float] = {}


def _emit(event: dict) -> None:
    sink = SINK.get()
    if sink is None:
        return
    try:
        sink(event)
    except Exception:  # tracing must never break a tool call
        pass


def _short(value: Any, limit: int = 90) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _label(tool: str, args: dict) -> str:
    """One-line description of the call's input."""
    a = args or {}
    if tool == "semantic_search":
        corpus = a.get("corpus", "complaints")
        where = f" @ {a['block_address']}" if a.get("block_address") else ""
        return f"{corpus}{where} · “{_short(a.get('query', ''), 60)}”"
    if tool == "analyze_photos":
        n = len(a.get("photo_ids") or [])
        return f"{n} tenant photo{'s' if n != 1 else ''}" + (f" · focus: {a['focus']}" if a.get("focus") else "")
    if tool == "resolve_date":
        return f"“{a.get('expression', '')}”"
    if tool == "locate_block":
        return a.get("block_address", "")
    if tool == "tract_context":
        return a.get("census_tract_geoid", "")
    if tool == "equity_audit":
        return ", ".join(a.get("census_tract_geoids") or [])
    if tool == "match_fund":
        parts = [f"{a.get('income_pct_ami')}% AMI", f"household {a.get('household_size')}"]
        if a.get("has_unlawful_detainer_case"):
            parts.append("UD case")
        parts.append("own DBI case" if a.get("has_open_habitability_case") else "no own DBI case")
        return " · ".join(parts)
    if tool == "submit_brief":
        return f"{len(a.get('evidence_request_ids') or [])} evidence · {len(a.get('statute_ids') or [])} statutes"
    if tool in SUB_AGENTS:
        return _short(a.get("request", a), 110)
    if tool == "execute_sql_readonly":
        return _short(a.get("query", ""), 110)
    return _short(a, 110)


def _summary(tool: str, resp: Any) -> tuple[str, bool]:
    """One-line description of the call's result, and whether it succeeded."""
    if tool in SUB_AGENTS:  # AgentTool returns the sub-agent's report as plain text
        failed = isinstance(resp, dict) and bool(resp.get("error"))
        return ("error: " + _short(resp["error"], 100)) if failed else "reported findings to the coordinator (click to read)", not failed
    if not isinstance(resp, dict):
        return _short(resp, 120), True
    if resp.get("error"):
        return f"error: {_short(resp['error'], 100)}", False
    if resp.get("status") == "error":
        return f"rejected: {_short('; '.join(resp.get('errors') or []), 100)}", False
    if resp.get("isError"):
        return "error from BigQuery MCP", False
    if tool == "semantic_search":
        m, x = resp.get("matches") or [], resp.get("excluded")
        if resp.get("corpus") == "complaints":
            decoys = sum(1 for e in (x or []) if e.get("planted_decoy"))
            return (f"{len(m)} matches · {len(x or [])} excluded ({decoys} planted decoys) · "
                    f"{resp.get('on_block_match_count', 0)} on the tenant's block"), True
        noun = "statutes" if resp.get("corpus") == "statutes" else "programs"
        return f"{len(m)} {noun}", True
    if tool == "analyze_photos":
        worst: dict[str, str] = {}
        rank = {"low": 0, "moderate": 1, "severe": 2}
        for p in resp.get("photos") or []:
            for h in p.get("hazards") or []:
                t, sv = h.get("type", "?"), h.get("severity", "low")
                if rank.get(sv, 0) >= rank.get(worst.get(t, "low"), 0):
                    worst[t] = sv
        found = " · ".join(f"{t.replace('_', ' ')} ({sv})" for t, sv in worst.items()) or "no visible hazards"
        return f"{found} · {resp.get('photo_count', 0)} photo(s)", True
    if tool == "resolve_date":
        s = f"{resp.get('weekday', '')} {resp.get('date', '')}".strip()
        return (s + " · ambiguous, asking") if resp.get("ambiguous") else s, True
    if tool == "locate_block":
        return f"tract {resp.get('census_tract_geoid')} · {resp.get('match', '')}", True
    if tool == "tract_context":
        t, mtr = resp.get("severe_rent_burden_pct"), resp.get("metro_severe_rent_burden_pct")
        side = "" if t is None or mtr is None else (" (higher)" if t > mtr else " (lower)")
        return f"severe rent burden {t}% vs {mtr}% metro{side} · {resp.get('annual_filings_modeled')} filings/yr (modeled)", True
    if tool == "match_fund":
        fits: dict[str, int] = {}
        for f in resp.get("funds") or []:
            k = f.get("fit") or ("likely" if f.get("eligible") else "not_eligible")
            fits[k] = fits.get(k, 0) + 1
        return " · ".join(f"{n} {k.replace('_', ' ')}" for k, n in fits.items()) or "no programs", True
    if tool in ("submit_brief", "add_equity_note"):
        b = resp.get("brief") or {}
        return f"brief ready · {len(b.get('evidence') or [])} evidence · {len(b.get('funds') or [])} funds", True
    if tool == "equity_audit":
        return f"{resp.get('selected_tract_count', '?')} tract vs {resp.get('metro_tract_count', '?')} metro tracts", True
    if tool in SUB_AGENTS:
        return "reported findings to the coordinator (click to read)", True
    if tool == "execute_sql_readonly":
        try:
            body = json.loads(resp["content"][0]["text"])
            return f"{body.get('totalRows', '?')} row(s)", True
        except Exception:
            return "query ran", True
    return _short(resp, 120), True


def _call_id(tool_context) -> str:
    return getattr(tool_context, "function_call_id", None) or f"{id(tool_context)}"


def before_tool(tool, args: dict, tool_context) -> None:
    """before_tool_callback: report that a call started. Never changes the call."""
    if SINK.get() is None:
        return None
    cid = _call_id(tool_context)
    _started[cid] = time.monotonic()
    _emit({
        "phase": "start", "id": cid, "agent": tool_context.agent_name, "tool": tool.name,
        "kind": "agent" if tool.name in SUB_AGENTS else "tool",
        "args": json.loads(json.dumps(args or {}, default=str)), "label": _label(tool.name, args),
    })
    return None


def after_tool(tool, args: dict, tool_context, tool_response: Any) -> None:
    """after_tool_callback: report the result summary and duration. Never changes the result."""
    if SINK.get() is None:
        return None
    cid = _call_id(tool_context)
    started = _started.pop(cid, None)
    summary, ok = _summary(tool.name, tool_response)
    detail = None
    if tool.name in SUB_AGENTS:  # the sub-agent's full report, shown when the row is expanded
        text = tool_response.get("result", tool_response) if isinstance(tool_response, dict) else tool_response
        detail = (text if isinstance(text, str) else json.dumps(text, default=str))[:4000]
    _emit({
        "phase": "end", "id": cid, "agent": tool_context.agent_name, "tool": tool.name,
        "kind": "agent" if tool.name in SUB_AGENTS else "tool",
        "summary": summary, "ok": ok, "detail": detail,
        "ms": int((time.monotonic() - started) * 1000) if started else None,
    })
    return None
