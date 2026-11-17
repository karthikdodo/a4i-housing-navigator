"""Agent runners. Both yield the same normalized events, so the API code doesn't care which runs.

    AgentEvent("status",  tool=..., text=...)          a tool call started
    AgentEvent("tool",    tool=..., args=..., result=...)  a tool returned (feeds the panel)
    AgentEvent("message", text=..., final=bool)         agent text; final=True carries the WHOLE reply
    AgentEvent("brief",   result=brief)                 submit_brief / add_equity_note succeeded

LiveRunner   runs the real ADK `navigator` agent from agent/ (Gemini + BigQuery).
MockRunner   replays a scripted intake from api/fixtures (no GCP needed). Select with
             A4I_AGENT_MODE=mock|live (default: live if google-adk imports, else mock).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from .cases import CaseState, load_demo_fixture

log = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parents[1]

# Fallback status text if the agent package isn't importable (mirrors agent.TOOL_STATUS_TEXT).
STATUS_TEXT = {
    "resolve_date": "Working out the date…",
    "semantic_search": "Searching 311 records, statutes, and funds…",
    "locate_block": "Finding the tenant's census tract…",
    "match_fund": "Checking emergency fund eligibility…",
    "tract_context": "Pulling neighborhood context…",
    "equity_audit": "Running the equity audit…",
    "submit_brief": "Writing the Stabilization Brief…",
    "add_equity_note": "Adding the equity note…",
    "execute_sql_readonly": "Querying BigQuery…",
}


@dataclass
class AgentEvent:
    kind: str
    tool: Optional[str] = None
    text: str = ""
    final: bool = False
    args: dict = field(default_factory=dict)
    result: Any = None


# ============================================================================ live (ADK)


class LiveRunner:
    """Runs agent/navigator's root_agent with ADK, one ADK session per case."""

    mode = "live"

    def __init__(self) -> None:
        agent_dir = str(REPO / "agent")
        if agent_dir not in sys.path:
            sys.path.insert(0, agent_dir)
        from google.adk.agents.run_config import RunConfig, StreamingMode  # noqa: F401
        from google.adk.runners import InMemoryRunner
        from navigator.agent import TOOL_STATUS_TEXT, root_agent

        self._RunConfig, self._StreamingMode = RunConfig, StreamingMode
        self.status_text = {**STATUS_TEXT, **TOOL_STATUS_TEXT}
        self.runner = InMemoryRunner(agent=root_agent, app_name="navigator")

    async def run(self, user_id: str, session_id: str, text: str, case: CaseState,
                  attachments: Optional[list[dict]] = None) -> AsyncIterator[AgentEvent]:
        from google.genai import types

        from .media import get_upload

        svc = self.runner.session_service
        if await svc.get_session(app_name="navigator", user_id=user_id, session_id=session_id) is None:
            await svc.create_session(app_name="navigator", user_id=user_id, session_id=session_id)

        parts = [types.Part(text=text)]
        for ph in attachments or []:  # tenant photos go to Gemini as images
            up, path = get_upload(ph["id"])
            parts.append(types.Part.from_bytes(data=path.read_bytes(), mime_type=up.mime))
        if attachments:
            parts.append(types.Part(text=(
                "The photos above were taken by the tenant. Describe only what is visible, say they are "
                "tenant-provided and not a public record or inspection finding, and never cite them as 311 evidence.")))
        message = types.Content(role="user", parts=parts)
        pending_args: dict[str, dict] = {}
        async for event in self.runner.run_async(
            user_id=user_id, session_id=session_id, new_message=message,
            run_config=self._RunConfig(streaming_mode=self._StreamingMode.SSE),
        ):
            trace_replayed = False  # replay specialist_trace once per event, not once per part
            for part in (event.content.parts if event.content else []) or []:
                if part.text and not getattr(part, "thought", False):
                    yield AgentEvent("message", text=part.text, final=not event.partial)
                elif event.partial:
                    continue  # SSE sends every function call twice; keep the final one only
                elif part.function_call:
                    name = part.function_call.name
                    pending_args[name] = dict(part.function_call.args or {})
                    yield AgentEvent("status", tool=name, text=self.status_text.get(name, "Working…"))
                elif part.function_response:
                    name = part.function_response.name
                    resp = part.function_response.response or {}
                    # Multi-agent mode: a specialist's inner tool calls aren't streamed; their raw
                    # results arrive in the state delta of the coordinator's function_response.
                    # Parallel calls put several function_responses in ONE event that shares one
                    # state_delta, so replaying per part would duplicate the specialist's results.
                    delta = (event.actions.state_delta or {}) if event.actions else {}
                    if not trace_replayed:
                        trace_replayed = True
                        for t in delta.get("specialist_trace") or []:
                            yield AgentEvent("tool", tool=t.get("tool"), args=t.get("args") or {},
                                             result=t.get("response"))
                    yield AgentEvent("tool", tool=name, args=pending_args.pop(name, {}), result=resp)
                    if name in ("submit_brief", "add_equity_note") and resp.get("status") == "ok":
                        yield AgentEvent("brief", result=resp["brief"])


# ============================================================================ mock (replay)

_MEMO = """## Intake memo — {case_id}

**To:** Supervising attorney · **Re:** {case_id}, nonpayment hearing {hearing}

**Facts.** Client {initials} (household of {household}) was served a 3-day pay-or-quit. She reports water under the floor outside her 4th-floor unit, spreading mold, and a heater that barely works.

**Evidence (block level).** The city record shows an open DBI case on the same block, **SF-202665044** (filed Nov 2, 2026) for water intrusion, plumbing leak and mold outside a 4th-floor unit, and a related open mold case in the adjacent tract (**SF-202665131**). A weaker hot-water record (SF-202665071) is listed but not relied on. Closed and commercial look-alikes were excluded (DECOY-SANF-05, -02, -01, -07).

**Law.** Habitability defense under Cal. Civ. Code § 1941.1 & § 1942.4 (needs an unabated citation on her unit for more than 35 days); anti-retaliation under § 1942.5; Prop F right to counsel.

**Funds.** Prop F Right to Counsel & Habitability Defense: likely fit. SF ERAP: needs household income. DBI Relocation & Mold Bridge: conditional on a notice for her unit.

**Next steps.** (1) File a unit-level DBI complaint today. (2) Refer to Prop F counsel. (3) Screen income for SF ERAP. (4) Collect photos, texts to the landlord and the rent ledger before the hearing.

**Caveats.** 311 records are redacted to the 100-block and do not prove conditions inside her unit. Eviction filing counts are modeled baselines."""


class MockRunner:
    """Scripted replay of the INT-1142 demo. Keyword routing, real data, fixed timings."""

    mode = "mock"

    def __init__(self, delay: float = float(os.getenv("A4I_MOCK_DELAY", "0.35"))) -> None:
        self.fx = load_demo_fixture()["tool_results"]
        self.delay = delay

    async def _sleep(self, k: float = 1.0) -> None:
        if self.delay:
            await asyncio.sleep(self.delay * k)

    async def _say(self, text: str) -> AsyncIterator[AgentEvent]:
        words = text.split(" ")
        chunk = max(6, len(words) // 6)
        acc = []
        for i in range(0, len(words), chunk):
            acc += words[i:i + chunk]
            yield AgentEvent("message", text=" ".join(words[i:i + chunk]) + " ", final=False)
            await self._sleep(0.25)
        yield AgentEvent("message", text=text, final=True)

    async def _tool(self, name: str, result: Any, args: Optional[dict] = None) -> AsyncIterator[AgentEvent]:
        yield AgentEvent("status", tool=name, text=STATUS_TEXT.get(name, "Working…"))
        await self._sleep(1.5)
        yield AgentEvent("tool", tool=name, args=args or {}, result=copy.deepcopy(result))

    def _brief(self, case: CaseState, memo: Optional[str] = None) -> dict:
        fx = self.fx
        statutes = fx["statutes"]["matches"]
        return {
            "case": {"block_address": case.block_address, "hazards": case.hazards,
                     "hearing_date": (case.hearing_datetime or "")[:10] or None,
                     "household_size": case.household_size, "income_pct_ami": case.income_pct_ami},
            "evidence": [{k: m.get(k) for k in ("request_id", "block_address", "census_tract_geoid", "raw_complaint_type",
                                                 "inspection_status", "created_date", "similarity", "on_tenant_block",
                                                 "narrative", "data_provenance")}
                         for m in fx["complaints"]["matches"]],
            "excluded": fx["complaints"]["excluded"],
            "statutes": [{"statute_section_id": s["statute_section_id"], "code_citation": s["code_citation"],
                          "ordinance_title": s["ordinance_title"], "protection": s["text"]} for s in statutes],
            "funds": fx["match_fund"]["funds"],
            "tract_context": {k: fx["tract_context"][k] for k in (
                "census_tract_geoid", "severe_rent_burden_pct", "metro_severe_rent_burden_pct", "annual_filings_modeled")},
            "equity_note": None,
            "cannot_prove": [
                "311 records show conditions on the block, not inside this tenant's unit",
                "Eviction filing counts are modeled neighborhood baselines, not court dockets",
                "No open heat complaint was found on her block; the heat claim rests on her account for now",
                "To close the gap: photos, texts to the landlord, rent ledger, and her own DBI complaint number",
            ],
            "memo_markdown": memo or _MEMO.format(
                case_id=case.case_id, hearing="Mon Nov 23, 9:00 AM", initials=case.client_initials,
                household=case.household_size or "?"),
            "stub_tools": [],
        }

    async def run(self, user_id: str, session_id: str, text: str, case: CaseState,
                  attachments: Optional[list[dict]] = None) -> AsyncIterator[AgentEvent]:
        t = text.lower()
        fx = self.fx
        if attachments:
            n = len(attachments)
            async for e in self._say(
                f"Added **{n} tenant photo{'s' if n != 1 else ''}** to the case file (Evidence tab, under the 311 records). "
                "In demo mode I can't look at images; with the live agent, Gemini describes what is visible. "
                "Photos are tenant-provided, not a public record: attach them to her own DBI complaint and the "
                "attorney packet, because they help close the gap between the block record and **her unit**."):
                yield e
            case.suggestions = ["Draft the intake memo"] if case.matches else ["Any open residential complaints on her block?"]
            return
        if case.case_id != "INT-1142" and "fixture" not in t:
            async for e in self._say(
                f"Demo mode only has recorded data for INT-1142 (600 Block John Muir Dr). For {case.case_id} I would "
                f"search 311 records near {case.block_address.split(',')[0] or 'the block'} for: {case.issue or text}. "
                "Set A4I_AGENT_MODE=live to run the real agent against BigQuery."):
                yield e
            return

        m = re.search(r"(DECOY-[A-Z]+-\d+|SF-\d+)", text, re.I)
        if m and ("why" in t or "exclude" in t):
            rid = m.group(1).upper()
            ex = {e["request_id"]: e for e in fx["complaints"]["excluded"]}.get(rid)
            if ex:
                async for e in self._say(
                    f"{rid} was excluded by the post-search filter: **{ex['reason']}**. It describes "
                    f"{ex['raw_complaint_type'].lower()} — “{ex['narrative'][:120]}…”. Habitability defenses and both "
                    "habitability-linked funds need an open, residential, un-abated case, so it can't support her "
                    "defense even though its similarity was high. See **Excluded by filter** in the Evidence tab."):
                    yield e
                return
        if "top raw match" in t or ("why" in t and "exclude" in t):
            top = max(fx["complaints"]["excluded"], key=lambda e: e["similarity"])
            async for e in self.run(user_id, session_id, f"Why did you exclude {top['request_id']}?", case):
                yield e
            return

        if not case.matches:  # first turn: the full intake run
            async for e in self._tool("resolve_date", {"date": "2026-11-23", "ambiguous": False, "in_past": False},
                                      {"text": "Monday"}):
                yield e
            async for e in self._tool("semantic_search", fx["complaints"],
                                      {"query": "water intrusion, mold, no heat", "corpus": "complaints",
                                       "block_address": case.block_address}):
                yield e
            async for e in self._say(
                "Yes. There is **one open residential record on the same block** and one in the adjacent tract that "
                "describe the same hazard:\n\n"
                "- **SF-202665044** · 600 Block John Muir Dr — water intrusion, plumbing leak, mold under floorboards "
                "outside a 4th-floor unit. Open – Active DBI Case since Nov 2.\n"
                "- **SF-202665131** · 500 Block Gonzalez Dr — mold in bathroom, bedroom and living room. Open – Active DBI Case.\n\n"
                "The highest raw match (similarity 0.89, DECOY-SANF-05) was excluded: it is a **closed, abated** mold case. "
                "I found no open heat complaint on her block.\n\n"
                "_Boundary: these records corroborate block conditions, not her specific unit._"):
                yield e
            case.suggestions = ["Why did you exclude the top raw match?", "Which statute bars the rent demand?",
                                "Which fund fits before Monday?", "How bad is eviction pressure here?"]
            return

        if "statute" in t or "law" in t or "defense" in t:
            async for e in self._tool("semantic_search", fx["statutes"],
                                      {"query": "habitability rent demand bar", "corpus": "statutes"}):
                yield e
            async for e in self._say(
                "**Cal. Civ. Code § 1941.1 & § 1942.4** (STAT-CA-01) bars a 3-day pay-or-quit while an official "
                "citation for untenantable conditions stays unabated past 35 days. It needs a citation on **her unit**: "
                "the block case opened Nov 2, so even that would be under 35 days. **§ 1942.5** (STAT-CA-03) adds a "
                "180-day anti-retaliation bar if she or a neighbor complained to DBI, and **SF Admin. Code Ch. 37 & Prop F** "
                "(STAT-CA-02) guarantees city-funded counsel."):
                yield e
            case.suggestions = ["Which fund fits before Monday?", "How bad is eviction pressure here?", "Draft the intake memo"]
            return

        if "fund" in t or "relief" in t or "money" in t:
            async for e in self._tool("match_fund", fx["match_fund"],
                                      {"income_pct_ami": None, "household_size": case.household_size,
                                       "has_open_habitability_case": True}):
                yield e
            async for e in self._say(
                "**Prop F Right to Counsel & Habitability Defense** is the likely fit: residential, and there is an open "
                "habitability case on her block. **SF ERAP** needs her household income (cap 80% AMI). The **DBI "
                "Relocation & Mold Bridge** is conditional: it needs an open notice on *her unit*, so file a 311/DBI "
                "complaint today. **MEDA** needs income and a wage-loss or medical-leave reason."):
                yield e
            case.suggestions = ["How bad is eviction pressure here?", "Draft the intake memo"]
            return

        if "tract" in t or "pressure" in t or "neighborhood" in t:
            async for e in self._tool("tract_context", fx["tract_context"], {"census_tract_geoid": "06075033204"}):
                yield e
            tc = fx["tract_context"]
            async for e in self._say(
                f"Tract 06075033204: **{tc['severe_rent_burden_pct']}%** of renter households pay 50%+ of income on rent, "
                f"vs **{tc['metro_severe_rent_burden_pct']}%** citywide. Nonpayment filings are about "
                f"**{tc['annual_filings_modeled']} a year** (modeled, summed over 4 quarters; "
                f"{tc['annual_filings_percentile']}th percentile of SF tracts). These are neighborhood baselines, not her docket."):
                yield e
            case.suggestions = ["Draft the intake memo"]
            return

        if "memo" in t or "brief" in t or "draft" in t:
            for name, result, args in (
                ("semantic_search", fx["statutes"], {"corpus": "statutes"}),
                ("match_fund", fx["match_fund"], {}),
                ("tract_context", fx["tract_context"], {"census_tract_geoid": "06075033204"}),
            ):
                if not _seen(case, name, args):
                    async for e in self._tool(name, result, args):
                        yield e
            brief = self._brief(case)
            async for e in self._tool("submit_brief", {"status": "ok", "brief": brief}):
                yield e
            yield AgentEvent("brief", result=brief)
            async for e in self._tool("equity_audit", fx["equity_audit"], {"census_tract_geoids": ["06075033204"]}):
                yield e
            note = ("Post-output audit: this tract's Hispanic and Black shares are well above the SF tract average. "
                    "Not used in ranking; flag for outreach in Spanish.")
            brief = {**brief, "equity_note": note}
            async for e in self._tool("add_equity_note", {"status": "ok", "brief": brief}):
                yield e
            yield AgentEvent("brief", result=brief)
            async for e in self._say(
                "The **Tenant Stabilization Brief** is ready, with the intake memo for the attorney. It cites "
                "SF-202665044, SF-202665131 and SF-202665071, three statutes and four funds, and lists what the record "
                "can't prove. Review the memo in the **Memo** tab, then open the Brief."):
                yield e
            case.suggestions = ["What should she bring to the hearing?"]
            return

        async for e in self._say(
            "Bring photos and videos of the water and mold with dates, texts or letters to the landlord about repairs, "
            "the rent ledger, the 3-day notice, and any DBI or 311 complaint number. Those close the gap between the "
            "block record and **her unit**."):
            yield e


def _seen(case: CaseState, name: str, args: dict) -> bool:
    if name == "semantic_search":
        return bool(case.statutes)
    if name == "match_fund":
        return bool(case.funds)
    if name == "tract_context":
        return bool(case.tract)
    return False


def make_runner() -> Any:
    mode = os.getenv("A4I_AGENT_MODE", "").lower()
    if mode == "mock":
        return MockRunner()
    try:
        return LiveRunner()
    except Exception as e:  # ImportError, missing credentials, ...
        if mode == "live":
            raise
        log.warning("Live agent unavailable (%s). Falling back to demo mode (A4I_AGENT_MODE=mock).", e)
        return MockRunner()
