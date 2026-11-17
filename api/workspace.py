"""One paralegal workspace per UI session: the intake queue, the open case, and its surfaces.

The workspace turns three kinds of input into one outbound event stream:
  * a chat message           -> agent turn (status / message / brief events) + A2UI updates
  * an A2UI `action`         -> local change (open case, mark reviewed) or an agent turn
  * a (re)connect            -> createSurface for every surface, plus the chat transcript

Outbound events (JSON, one per WebSocket frame or SSE `data:` line):
  {"type": "status",  "tool", "text"}                      tool started (docs/ARCHITECTURE.md)
  {"type": "message", "text", "final"}                     agent text (final = whole reply)
  {"type": "brief",   "brief"}                             Stabilization Brief JSON
  {"type": "error",   "text"}
  {"type": "a2ui",    "messages": [ ...A2UI v1.0 agent-to-renderer messages... ]}
  {"type": "case",    "case_id", "transcript", "mode"}     the open case changed (redraw chat)
  {"type": "user_echo", "text"}                            a UI action became a chat question
  {"type": "user_turn", "turn"}                            the user turn as stored (text, photos, voice clip)
  {"type": "turn_end"}
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, AsyncIterator, Optional

from .a2ui import surfaces as S
from .a2ui import view as V
from .cases import CaseState, ChatTurn, demo_queue, new_case_id, now
from .media import get_upload
from .runners import AgentEvent

log = logging.getLogger(__name__)

ID_RE = re.compile(r"\b(?:SF-\d{6,}|DECOY-[A-Z]{4}-\d{2}|STAT-[A-Z]{2}-\d{2}|BUL-[A-Z]{2}-\d{2})\b")

TAB_FOR_TOOL = {"semantic_search": "evidence", "match_fund": "funds", "tract_context": "tract",
                "submit_brief": "memo", "add_equity_note": "memo"}

# Actions the browser handles itself; the server ignores them if they arrive.
CLIENT_ONLY_ACTIONS = {"open_brief", "close_brief", "print_brief", "copy_memo", "open_intake_form", "close_intake_form"}


class Workspace:
    def __init__(self, session_id: str, runner: Any) -> None:
        self.session_id = session_id
        self.runner = runner
        self.cases: dict[str, CaseState] = demo_queue()
        self.active_id: str = "INT-1142"
        self.focus_seq = 0
        self.lock = asyncio.Lock()
        for c in self.cases.values():
            c.suggestions = V.default_suggestions(c)
        self.cases[self.active_id].suggestions = [
            "Any open residential complaints on her block?",
            "Which statute bars the rent demand?",
            "Which fund fits before Monday?",
        ]

    # ------------------------------------------------------------------ helpers
    @property
    def case(self) -> CaseState:
        return self.cases[self.active_id]

    def memo_url(self) -> str:
        return f"/api/sessions/{self.session_id}/cases/{self.active_id}/memo.md"

    def models(self) -> dict[str, dict]:
        c = self.case
        docs = V.documents_model(c)
        docs["memo_url"] = self.memo_url()
        docs["focus_seq"] = self.focus_seq
        return {
            S.QUEUE: V.queue_model(self.cases, self.active_id),
            S.HEADER: V.header_model(c),
            S.MAP: V.map_model(c),
            S.SUGGESTIONS: V.suggestions_model(c),
            S.DOCUMENTS: docs,
            S.BRIEF: V.brief_model(c),
            S.INTAKE_FORM: V.intake_form_model(),
        }

    def snapshot(self) -> list[dict]:
        """createSurface for every surface: what a freshly connected renderer needs."""
        return [S.create_surface(sid, model) for sid, model in self.models().items()]

    def updates(self, surface_ids: tuple[str, ...] = (S.QUEUE, S.HEADER, S.MAP, S.SUGGESTIONS, S.DOCUMENTS, S.BRIEF)) -> dict:
        m = self.models()
        return {"type": "a2ui", "messages": [S.update_data_model(sid, m[sid]) for sid in surface_ids]}

    def case_event(self) -> dict:
        return {"type": "case", "case_id": self.active_id, "mode": self.runner.mode,
                "transcript": [t.to_json() for t in self.case.transcript],
                "trace": self.case.trace}

    # ------------------------------------------------------------------ inputs
    async def connect(self) -> list[dict]:
        return [{"type": "a2ui", "messages": self.snapshot()}, self.case_event()]

    async def user_message(self, text: str, echo: bool = False, attachments: Optional[list[str]] = None,
                           voice: Optional[dict] = None) -> AsyncIterator[dict]:
        """One chat turn. `attachments` = upload ids of photos; `voice` = {id, duration, source} of the
        recorded clip the text was transcribed from (shown with the transcript in the chat history)."""
        text = (text or "").strip()
        photos = self._resolve_photos(attachments or [])
        if not text and not photos:
            return
        if not text:
            text = f"I've attached {len(photos)} photo{'s' if len(photos) != 1 else ''} from the tenant."
        voice_turn = self._resolve_voice(voice)
        async with self.lock:
            c = self.case
            c.begin_turn()
            turn = ChatTurn("user", text, attachments=photos, voice=voice_turn)
            c.transcript.append(turn)
            for ph in photos:
                if ph["id"] not in {p["id"] for p in c.photos}:
                    c.photos.append({**ph, "added_at": now().isoformat()})
            if echo:
                yield {"type": "user_echo", "text": text}
            yield {"type": "user_turn", "turn": turn.to_json()}
            if photos:
                yield self.updates((S.DOCUMENTS, S.BRIEF))
            reply = ""
            before = list(c.suggestions)
            adk_session = f"{self.session_id}:{c.case_id}"
            try:
                async for ev in self.runner.run(self.session_id, adk_session, self._with_case_context(c, text), c,
                                                attachments=photos):
                    for out in self._on_agent_event(c, ev):
                        yield out
                    if ev.kind == "message" and ev.final:
                        reply = ev.text
            except Exception as e:  # never leave the UI hanging
                log.exception("agent turn failed")
                yield {"type": "error", "text": f"The navigator hit an error: {e}"}
            if reply:
                c.transcript.append(ChatTurn("agent", reply, citations=sorted(set(ID_RE.findall(reply)))))
            if c.suggestions == before:  # the runner didn't propose follow-ups: derive them from progress
                c.suggestions = V.default_suggestions(c)
            yield self.updates()
            yield {"type": "turn_end"}

    async def action(self, action: dict) -> AsyncIterator[dict]:
        """Handle an A2UI v1.0 renderer-to-agent `action` (the inner object)."""
        name = action.get("name", "")
        ctx = action.get("context") or {}
        if name in CLIENT_ONLY_ACTIONS:
            return
        if name == "ask":
            async for out in self.user_message(str(ctx.get("text", "")), echo=True):
                yield out
        elif name == "explain_exclusion":
            rid = str(ctx.get("request_id", ""))
            self._focus(rid, "evidence")
            yield self.updates((S.DOCUMENTS,))
            async for out in self.user_message(f"Why did you exclude {rid}? It looked similar to her conditions.", echo=True):
                yield out
        elif name == "focus_record":
            rid = str(ctx.get("request_id", ""))
            self._focus(rid, self._tab_for_id(rid))
            yield self.updates((S.DOCUMENTS,))
        elif name == "open_case":
            cid = str(ctx.get("case_id", ""))
            if cid in self.cases:
                self.active_id = cid
                yield self.updates()
                yield self.case_event()
        elif name == "mark_memo_reviewed":
            if self.case.memo_markdown:
                self.case.memo_status = "reviewed"
                if self.case.brief:
                    self.case.refresh_queue_status()
            # The case header (stage 8 "Memo & review") and the queue show review status too.
            yield self.updates((S.HEADER, S.QUEUE, S.DOCUMENTS, S.BRIEF))
        elif name == "submit_intake":
            async for out in self._submit_intake(ctx):
                yield out
        else:
            yield {"type": "error", "text": f"Unknown action {name!r}"}

    # ------------------------------------------------------------------ voice + photos
    def _resolve_photos(self, ids: list[str]) -> list[dict]:
        out = []
        for uid in ids[:6]:
            try:
                up, _ = get_upload(str(uid))
            except FileNotFoundError:
                continue
            if up.kind == "image":
                out.append({"id": up.id, "url": up.url, "kind": "image", "name": up.name, "mime": up.mime})
        return out

    def _resolve_voice(self, voice: Optional[dict]) -> Optional[dict]:
        if not voice or not voice.get("id"):
            return None
        try:
            up, _ = get_upload(str(voice["id"]))
        except FileNotFoundError:
            return None
        if up.kind != "audio":
            return None
        return {"id": up.id, "url": up.url, "duration": float(voice.get("duration") or 0),
                "source": str(voice.get("source") or "")}

    def intake_form_patch(self, fields: dict) -> dict:
        """A2UI updateDataModel messages that fill the New intake form with fields heard by voice."""
        msgs = []
        for key in ("client", "block", "issue", "hearing", "household", "ami"):
            if fields.get(key):
                msgs.append(S.update_data_model(S.INTAKE_FORM, str(fields[key]), f"/form/{key}"))
        if fields.get("notice"):
            msgs.append(S.update_data_model(S.INTAKE_FORM, [fields["notice"]], "/form/notice"))
        return {"type": "a2ui", "messages": msgs}

    # ------------------------------------------------------------------ internals
    def _with_case_context(self, c: CaseState, text: str) -> str:
        """First message of a case carries the intake facts, so the agent doesn't ask again."""
        if len(c.transcript) > 1 or not c.block_address:
            return text
        facts = [f"Case {c.case_id}. Tenant {c.client_initials}", f"block: {c.block_address}"]
        if c.issue:
            facts.append(f"reported conditions: {c.issue}")
        if c.hearing_datetime:
            facts.append(f"hearing: {c.hearing_datetime}")
        if c.notice_type:
            facts.append(f"notice: {c.notice_type}")
        if c.household_size:
            facts.append(f"household of {c.household_size}")
        if c.income_pct_ami is not None:
            facts.append(f"{c.income_pct_ami:g}% AMI")
        return "[Intake facts] " + "; ".join(facts) + ".\n\n" + text

    def _focus(self, rid: str, tab: str) -> None:
        self.case.focus_id = rid
        self.case.active_tab = tab
        self.focus_seq += 1

    def _tab_for_id(self, rid: str) -> str:
        if rid.startswith("STAT-"):
            return "statutes"
        if rid.startswith("BUL-"):
            return "funds"
        return "evidence"

    def _on_agent_event(self, c: CaseState, ev: AgentEvent) -> list[dict]:
        if ev.kind == "status":
            c.transcript.append(ChatTurn("status", ev.text, tool=ev.tool))
            return [{"type": "status", "tool": ev.tool, "text": ev.text}]
        if ev.kind == "message":
            return [{"type": "message", "text": ev.text, "final": ev.final}]
        if ev.kind == "tool":
            changed = c.apply_tool_result(ev.tool or "", ev.result, ev.args)
            if not changed:
                return []
            tab = TAB_FOR_TOOL.get(ev.tool or "")
            if ev.tool == "semantic_search" and "statutes" in changed:
                tab = "statutes"
            if tab:
                c.active_tab = tab
                self.focus_seq += 1
            summary = _tool_summary(ev)
            if summary:
                c.transcript.append(ChatTurn("status", summary, tool=ev.tool))
            out = [self.updates()]
            if summary:
                out.insert(0, {"type": "status", "tool": ev.tool, "text": summary, "done": True})
            return out
        if ev.kind == "brief":
            c.apply_brief(ev.result)
            return [{"type": "brief", "brief": ev.result}, self.updates()]
        if ev.kind == "trace":
            # Live agent activity: every tool call by the coordinator and its sub-agents.
            turn = sum(1 for t in c.transcript if t.role == "user")
            item = {**(ev.result or {}), "turn": turn}
            c.trace.append(item)
            return [{"type": "trace", **item}]
        return []

    async def _submit_intake(self, ctx: dict) -> AsyncIterator[dict]:
        block = str(ctx.get("block") or "").strip()
        issue = str(ctx.get("issue") or "").strip()
        if not block or not issue:
            yield {"type": "error", "text": "Block and issue are required to open a case."}
            return
        notice = ctx.get("notice")
        notice = notice[0] if isinstance(notice, list) and notice else (notice or "")
        notice_label = {o["value"]: o["label"] for o in S.NOTICE_OPTIONS}.get(notice, "")
        c = CaseState(
            case_id=new_case_id(),
            client_initials=_initials(str(ctx.get("client") or "")) or "Client",
            household_size=_int(ctx.get("household")),
            income_pct_ami=_float(ctx.get("ami")),
            block_address=block if "san francisco" in block.lower() else f"{block}, San Francisco, CA",
            issue=issue,
            hazards=_hazards(issue),
            hearing_datetime=(str(ctx.get("hearing") or "")[:16] or None),
            notice_type=notice_label,
        )
        self.cases[c.case_id] = c
        self.active_id = c.case_id
        yield self.updates(S.SURFACES)
        yield self.case_event()
        async for out in self.user_message(f"New intake. {issue.rstrip('.')}. Are there open residential complaints on this block?", echo=True):
            yield out


def _tool_summary(ev: AgentEvent) -> str:
    r = ev.result if isinstance(ev.result, dict) else {}
    if ev.tool == "semantic_search" and (r.get("corpus") == "complaints"):
        return (f"semantic_search · AI.EMBED + VECTOR_SEARCH → post-filter → "
                f"{len(r.get('matches', []))} kept · {len(r.get('excluded', []))} excluded")
    if ev.tool == "semantic_search" and r.get("corpus") == "statutes":
        return f"semantic_search(statutes) · {len(r.get('matches', []))} statutes matched"
    if ev.tool == "match_fund":
        return f"match_fund · {len(r.get('funds', []))} SF funds checked by rule"
    if ev.tool == "tract_context":
        return "tract_context · ACS + filings summed over 4 quarters"
    return ""


def _initials(s: str) -> str:
    s = s.strip()
    if re.fullmatch(r"([A-Za-z]\.?\s?){1,3}", s):
        letters = re.findall(r"[A-Za-z]", s)
        return ".".join(x.upper() for x in letters) + "."
    return "".join(w[0].upper() + "." for w in s.split()[:3])  # never keep a full name


def _int(v: Any) -> Optional[int]:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_HAZARD_WORDS = {"mold": "mold", "heat": "no heat", "leak": "leak", "water": "water intrusion", "sewage": "sewage",
                 "wiring": "exposed wiring", "pest": "pests", "roach": "pests", "rodent": "pests", "fire": "fire damage",
                 "power": "no power", "sink": "plumbing"}


def _hazards(issue: str) -> list[str]:
    low = issue.lower()
    out = []
    for k, v in _HAZARD_WORDS.items():
        if k in low and v not in out:
            out.append(v)
    return out or ["habitability issue"]
