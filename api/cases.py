"""Case state for the intake workspace.

One `CaseState` per intake case. It folds every tool result and the brief into one place so
the A2UI surfaces (api/a2ui/) can be rebuilt from it at any time, in any order. Nothing here
calls the model or BigQuery: it only records what the agent's tools returned.

Trust rules carried in code (see docs/AGENT_REQUIREMENTS.md):
  * Evidence shown in the panel comes only from semantic_search `matches` or the brief.
  * Excluded rows are kept and always shown, with their reason.
  * census_tract_geoid stays a string end to end.
  * audit_* data (equity_audit) is stored separately and only rendered in the Brief.
"""

from __future__ import annotations

import copy
import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
FIXTURES = Path(__file__).with_name("fixtures")


def now() -> datetime:
    return datetime.now(TZ)


@dataclass
class ChatTurn:
    role: str  # "user" | "agent" | "status"
    text: str
    tool: Optional[str] = None
    citations: list[str] = field(default_factory=list)
    attachments: list[dict] = field(default_factory=list)  # [{id, url, kind, name}] photos sent with the message
    voice: Optional[dict] = None  # {id, url, duration, source} when the message was spoken

    def to_json(self) -> dict:
        return {"role": self.role, "text": self.text, "tool": self.tool, "citations": self.citations,
                "attachments": self.attachments, "voice": self.voice}


@dataclass
class CaseState:
    case_id: str
    client_initials: str = ""
    household_size: Optional[int] = None
    block_address: str = ""
    issue: str = ""
    hazards: list[str] = field(default_factory=list)
    hearing_datetime: Optional[str] = None  # ISO local, "2026-11-23T09:00" or "2026-11-23"
    notice_type: str = ""
    income_pct_ami: Optional[float] = None
    census_tract_geoid: Optional[str] = None
    opened_at: datetime = field(default_factory=now)
    queue_status: str = "Not yet searched"
    cited_count: int = 0  # records the latest brief cites (queue label)
    queue_status_tone: str = "neutral"
    flag: str = ""

    # Accumulated tool output
    matches: dict[str, dict] = field(default_factory=dict)
    excluded: dict[str, dict] = field(default_factory=dict)
    statutes: dict[str, dict] = field(default_factory=dict)
    funds: list[dict] = field(default_factory=list)
    tract: Optional[dict] = None
    equity: Optional[dict] = None
    brief: Optional[dict] = None
    photos: list[dict] = field(default_factory=list)  # tenant-provided, not a public record
    photo_query: str = ""  # analyze_photos' 311-style description of what the photos show
    tools_run: set[str] = field(default_factory=set)
    stub_tools: set[str] = field(default_factory=set)
    trace: list[dict] = field(default_factory=list)  # live agent/tool trace events, tagged by turn

    memo_status: str = "draft"  # draft | reviewed
    memo_markdown: str = ""
    brief_prepared_at: Optional[datetime] = None

    transcript: list[ChatTurn] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    focus_id: Optional[str] = None
    active_tab: str = "evidence"
    changed_this_turn: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------ tool results
    def begin_turn(self) -> None:
        self.changed_this_turn = set()

    def apply_tool_result(self, name: str, response: Any, args: Optional[dict] = None) -> list[str]:
        """Fold one tool result in. Returns the panel sections that changed."""
        if not isinstance(response, dict) or response.get("error"):
            return []
        args = args or {}
        self.tools_run.add(name)
        if response.get("stub"):
            self.stub_tools.add(name)
        changed: list[str] = []

        if name == "semantic_search":
            corpus = response.get("corpus") or args.get("corpus") or "complaints"
            if corpus == "complaints":
                for m in response.get("matches", []):
                    rid = m["request_id"]
                    if rid not in self.matches:
                        self.changed_this_turn.add(rid)
                    self.matches[rid] = m
                    if m.get("on_tenant_block") and not self.census_tract_geoid and m.get("census_tract_geoid"):
                        self.census_tract_geoid = str(m["census_tract_geoid"])
                for e in response.get("excluded", []):
                    self.excluded[e["request_id"]] = e
                on_block = sum(1 for m in self.matches.values() if m.get("on_tenant_block"))
                if not self.brief:
                    self.queue_status = (f"{on_block} open block record{'s' if on_block != 1 else ''} found" if on_block
                                         else f"{len(self.matches)} nearby open record{'s' if len(self.matches) != 1 else ''}, none on block")
                    self.queue_status_tone = "eligible" if on_block else "excluded"
                changed.append("evidence")
            elif corpus == "statutes":
                for s in response.get("matches", []):
                    sid = s["statute_section_id"]
                    if sid not in self.statutes:
                        self.changed_this_turn.add(sid)
                    self.statutes[sid] = s
                changed.append("statutes")
        elif name == "locate_block":
            if response.get("census_tract_geoid") and not self.census_tract_geoid:
                self.census_tract_geoid = str(response["census_tract_geoid"])
                changed.append("header")
        elif name == "match_fund":
            self.funds = list(response.get("funds", []))
            self.changed_this_turn.update(f.get("program_name", "") for f in self.funds)
            changed.append("funds")
        elif name == "tract_context":
            self.tract = dict(response)
            if response.get("census_tract_geoid"):
                self.census_tract_geoid = str(response["census_tract_geoid"])
            changed.append("tract")
        elif name == "analyze_photos":
            # Gemini vision findings, attached to the tenant's photos (still not 311 evidence).
            by_id = {p.get("photo_id"): p for p in response.get("photos") or []}
            for ph in self.photos:
                found = by_id.get(ph.get("id"))
                if found:
                    ph["caption"] = found.get("summary", "")
                    ph["hazards"] = [
                        {k: h.get(k) for k in ("type", "severity", "where", "confidence", "visible_evidence")}
                        for h in found.get("hazards") or []]
                    ph["people_visible"] = bool(found.get("people_or_personal_info_visible"))
                    ph["analyzed"] = True
            self.photo_query = response.get("suggested_311_query", "")
            changed.append("evidence")
        elif name == "equity_audit":
            self.equity = dict(response)
            changed.append("brief")
        elif name == "resolve_date":
            date = response.get("date") or response.get("resolved_date")
            if date and not response.get("ambiguous") and not response.get("in_past"):
                time_part = self.hearing_datetime[10:] if self.hearing_datetime and len(self.hearing_datetime) > 10 else ""
                self.hearing_datetime = str(date) + time_part
                changed.append("header")
        elif name in ("submit_brief", "add_equity_note") and response.get("status") == "ok":
            self.apply_brief(response["brief"])
            changed += ["header", "evidence", "statutes", "funds", "tract", "memo", "brief"]
        return changed

    def apply_brief(self, brief: dict) -> None:
        self.brief = copy.deepcopy(brief)
        self.brief_prepared_at = now()
        case = brief.get("case") or {}
        self.block_address = case.get("block_address") or self.block_address
        self.hazards = case.get("hazards") or self.hazards
        if case.get("hearing_date"):
            hd = str(case["hearing_date"])
            if not (self.hearing_datetime and self.hearing_datetime.startswith(hd)):
                self.hearing_datetime = hd
        self.household_size = case.get("household_size") or self.household_size
        if case.get("income_pct_ami") is not None:
            self.income_pct_ami = case["income_pct_ami"]
        if brief.get("funds"):
            self.funds = brief["funds"]
        tc = brief.get("tract_context")
        if tc:
            self.tract = {**(self.tract or {}), **{k: v for k, v in tc.items() if v is not None}}
            self.census_tract_geoid = str(tc.get("census_tract_geoid") or self.census_tract_geoid or "") or None
        new_memo = brief.get("memo_markdown") or ""
        if new_memo and new_memo != self.memo_markdown:
            self.memo_markdown = new_memo
            self.memo_status = "draft"
        for s in brief.get("statutes", []):
            sid = s.get("statute_section_id")
            if sid and sid in self.statutes:
                self.statutes[sid] = {**self.statutes[sid], **{k: v for k, v in s.items() if v}}
        self.stub_tools.update(brief.get("stub_tools") or [])
        if self.matches or brief.get("evidence"):
            self.cited_count = len(brief.get("evidence") or [])
            self.refresh_queue_status()

    def refresh_queue_status(self) -> None:
        """Queue label after a brief: the memo's review state first, then what the brief cites."""
        n = self.cited_count
        cited = f"{n} record{'s' if n != 1 else ''} cited" if n else "no open record on block"
        if self.memo_status == "reviewed":
            self.queue_status, self.queue_status_tone = f"Ready for attorney · {cited}", "eligible"
        else:
            self.queue_status, self.queue_status_tone = f"Needs review · {cited}", "excluded"

    # ------------------------------------------------------------------ derived
    @property
    def evidence_rows(self) -> list[dict]:
        """Brief evidence when a brief exists (the cited, verified subset), else all matches."""
        if self.brief and self.brief.get("evidence") is not None:
            rows = []
            for e in self.brief["evidence"]:
                rows.append({**self.matches.get(e["request_id"], {}), **{k: v for k, v in e.items() if v is not None}})
            return rows
        return sorted(self.matches.values(), key=lambda r: -float(r.get("similarity") or 0))

    @property
    def excluded_rows(self) -> list[dict]:
        rows = dict(self.excluded)
        if self.brief:
            for e in self.brief.get("excluded") or []:
                rows[e["request_id"]] = {**rows.get(e["request_id"], {}), **e}
        return sorted(rows.values(), key=lambda r: -float(r.get("similarity") or 0))

    def raw_rank(self, request_id: str) -> Optional[int]:
        """Rank of a record among ALL vector-search candidates, before the decoy filter."""
        allrows = {**{k: v.get("similarity") for k, v in self.matches.items()},
                   **{k: v.get("similarity") for k, v in self.excluded.items()}}
        ordered = sorted(allrows, key=lambda k: -float(allrows[k] or 0))
        return ordered.index(request_id) + 1 if request_id in ordered else None

    def to_json(self) -> dict:
        return {
            "case_id": self.case_id,
            "client_initials": self.client_initials,
            "household_size": self.household_size,
            "block_address": self.block_address,
            "issue": self.issue,
            "hazards": self.hazards,
            "hearing_datetime": self.hearing_datetime,
            "notice_type": self.notice_type,
            "income_pct_ami": self.income_pct_ami,
            "census_tract_geoid": self.census_tract_geoid,
            "tools_run": sorted(self.tools_run),
            "stub_tools": sorted(self.stub_tools),
            "memo": {"status": self.memo_status, "markdown": self.memo_markdown},
            "brief": self.brief,
            "transcript": [t.to_json() for t in self.transcript],
            "suggestions": self.suggestions,
            "photos": self.photos,
        }


# ---------------------------------------------------------------------- the intake queue
_ids = itertools.count(1143)


def demo_queue() -> dict[str, CaseState]:
    """Today's intake queue. Initials and blocks only: no names, no unit numbers."""
    cases = [
        CaseState(case_id="INT-1142", client_initials="M.R.", household_size=3,
                  block_address="600 Block John Muir Dr, San Francisco, CA",
                  issue="Water under the floorboards outside her 4th-floor unit, spreading mold, heater barely works.",
                  hazards=["mold", "water intrusion", "low heat"], hearing_datetime="2026-11-23T09:00",
                  notice_type="3-day pay-or-quit (nonpayment)"),
        CaseState(case_id="INT-1137", client_initials="J.T.", household_size=1,
                  block_address="1300 Block 46th Av, San Francisco, CA",
                  issue="No working kitchen sink and exposed wiring in a shared unit.",
                  hazards=["no sink", "exposed wiring"], hearing_datetime=None,
                  notice_type="3-day pay-or-quit (nonpayment)", flag="3-day notice"),
        CaseState(case_id="INT-1139", client_initials="D.K.", household_size=2,
                  block_address="2900 Block Ulloa St, San Francisco, CA",
                  issue="Kitchen fire last month, no power in two rooms since.",
                  hazards=["fire damage", "no power"], hearing_datetime="2026-11-29T13:30",
                  notice_type="Unlawful detainer (nonpayment)"),
        CaseState(case_id="INT-1131", client_initials="A.L.", household_size=4,
                  block_address="1400 Block 26th Av, San Francisco, CA",
                  issue="Ceiling leak; landlord told her not to report it.",
                  hazards=["ceiling leak"], hearing_datetime=None, notice_type="None served yet",
                  flag="Retaliation risk"),
    ]
    for c in cases:
        if c.flag == "Retaliation risk":
            c.queue_status, c.queue_status_tone = "Retaliation risk flagged", "excluded"
    return {c.case_id: c for c in cases}


def new_case_id() -> str:
    return f"INT-{next(_ids)}"


def load_demo_fixture() -> dict:
    return json.loads((FIXTURES / "demo_int_1142.json").read_text())
