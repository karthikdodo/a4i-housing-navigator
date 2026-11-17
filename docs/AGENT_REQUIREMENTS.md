# Agent requirements: what the `navigator` agent must do for the A2UI case workspace

**Owners:** Karthik (`agent.py`, `prompts.py`, `brief.py`), Prachi (`tools/match_fund.py`, `tracts`, `equity_audit`), Sid (`locate_block`, deploy)
**Readers:** anyone changing the agent, its tools, or the brief JSON
**Related:** [`UI_API.md`](UI_API.md) (API + A2UI surfaces) · [`ARCHITECTURE.md`](ARCHITECTURE.md) (tools, decoy filter, WebSocket contract) · the UI design canvas (Spec, Main, Brief)

The UI is a three-zone case workspace built with Google's **A2UI** (Agent-to-User Interface) protocol, v1.0. The API (`api/`) runs the ADK agent, folds every tool result into a case state, and sends **A2UI surfaces** to the browser. The agent never writes UI: it calls tools and writes text. That split is deliberate, because the panel must only ever show records a tool actually returned.

This page lists what the agent has to provide so the screens work, what it already provides, and what the API does in the meantime.

---

## 1. How the agent's output reaches the screen

```
paralegal ─chat / A2UI action─► api/workspace.py ─text─► ADK runner ─► navigator agent (Gemini)
                                      ▲                                     │ tool calls
                                      │ tool results, text, brief           ▼
                                      └──────────── CaseState ◄──── semantic_search, match_fund, …
                                                       │
                                      api/a2ui/view.py + surfaces.py
                                                       │  A2UI v1.0: createSurface / updateDataModel
                                                       ▼
                                      ui/ (React + @a2ui/react renderer + navigator catalog)
```

| Agent output | What the API does with it | Where it shows |
|---|---|---|
| `function_call` (any tool) | `status` event with `TOOL_STATUS_TEXT[name]` | Tool-trace line in chat |
| `semantic_search(corpus="complaints")` result | `matches` → Evidence cards, `excluded` → "Excluded by filter" drawer, raw rank computed across both | Evidence tab, case header tract, queue status |
| `semantic_search(corpus="statutes")` result | Statute cards, sorted by similarity | Statutes tab |
| `match_fund` result | Fund cards with fit label | Funds tab |
| `tract_context` result | Stat tiles (real vs **modeled** tag) | Tract tab |
| `equity_audit` result | Equity table, **Brief only** | Brief §4 |
| `submit_brief` / `add_equity_note` with `status: "ok"` | Replaces evidence with the cited subset, memo, `brief` event | Memo tab, Brief overlay, progress steps |
| Final text of the turn | Markdown with record-id chips | Chat |

---

## 2. Requirements

Status: **Met** = works with the agent on `main` today · **Partial** = works, the API fills a gap · **Gap** = the agent must change.

### Conversation

| # | Requirement | Status | Notes |
|---|---|---|---|
| R1 | One ADK session per case. Follow-up questions about the same case keep the evidence in session state. | Met | The API uses `session_id = "<ui-session>:<case-id>"`. Switching cases in the queue switches sessions. |
| R2 | Accept the intake facts the paralegal already typed, and don't ask for them again. | Partial | The first message of a case is prefixed with `[Intake facts] Case INT-1142. Tenant M.R.; block: …; hearing: 2026-11-23T09:00; notice: …; household of 3; 45% AMI.` **Prompt change:** treat that line as facts the paralegal gave (workflow step 1). |
| R3 | Answer a narrow follow-up with a narrow answer. "Which fund fits before Monday?" should not rewrite the whole brief. | Gap | Workflow step 8 says "reply once, at the end", which suits the first turn. Add: *for a follow-up about one section, call only the tools that section needs, answer in 2–5 lines, and call `submit_brief` again only if the evidence, statutes, funds or memo changed.* |
| R4 | Explain an exclusion when asked. The UI sends "Why did you exclude DECOY-SANF-02? It looked similar to her conditions." from the **Ask why** button. | Met | Prompt already says to explain from the exclusion reason. Name the failing field (property type, closed date, no-violation status). |
| R5 | New facts mid-conversation ("actually it's the 700 block", "hearing moved to Thursday") re-run the affected tools and resubmit the brief. | Partial | Works when the model re-calls tools. Add to the prompt: *when the block, hearing date, income or household changes, re-run the tools that depend on it and call submit_brief again.* The UI marks changed cards **Updated**. |
| R6 | Hearing ≤ 72 h away: put same-day steps and defenses first in the reply and the memo. | Gap | The header already switches its text at 72 h. Add the ordering rule to the prompt. |

### Citations and evidence

| # | Requirement | Status | Notes |
|---|---|---|---|
| R7 | Cite records by exact id: `SF-202665044`, `DECOY-SANF-05`, `STAT-CA-01`, `BUL-CA-02`. | Partial | The chat turns these into chips that open the record in the panel (`focus_record`). Statutes are often cited by code citation only: **add the `statute_section_id` after the citation**, and the `bulletin_id` after a fund name. |
| R8 | Never cite an excluded record as evidence. | Met | `submit_brief` rejects excluded or unknown ids. The API also only renders evidence from `matches` or the brief. |
| R9 | Excluded rows carry the fields that excluded them. | **Gap** | `semantic_search` returns `request_id, reason, similarity, block_address, raw_complaint_type, planted_decoy`. Add **`property_type`, `inspection_status`, `closed_date`, and the first 300 characters of `narrative`** so the drawer can show "closed_date = 2026-07-09 → not an active hazard" and a one-line description. The API parses `reason` as a fallback. |
| R10 | Raw rank of every candidate before filtering. | Met (API) | The API ranks `matches ∪ excluded` by similarity, so "raw #1 · 0.89" works without agent changes. |

### Tools and their return shapes

| # | Requirement | Status | Change |
|---|---|---|---|
| R11 | `match_fund` returns a **fit** for each of the 4 SF funds, not just `eligible`. | **Gap** | Add `fit: "likely" \| "conditional" \| "needs_info" \| "not_eligible"`, `missing_inputs: ["income_pct_ami" \| "unit_dbi_complaint" \| "wage_loss_or_medical_leave" \| "household_size"]`, `bulletin_id`, `residential_tenants_only`. Make `income_pct_ami` and `household_size` **optional**: when unknown, return `needs_info` for AMI-capped funds instead of not running. Then workflow step 4 can always call it, and the Funds tab never sits empty. Rules stay in code (no LLM). |
| R12 | `tract_context` returns the four tiles the Tract tab shows. | **Gap** | Keep the current keys and add `annual_filings_percentile` (rank among SF tracts), `median_claimed_arrears_usd` + `arrears_quarter` (latest quarter, modeled), `poverty_rate_pct`, `metro_poverty_rate_pct`. Sum the 4 quarters **before** any join; keep the GEOID a string. |
| R13 | `equity_audit` returns a table the Brief can print. | **Gap** | `{"rows": [{"group": "Hispanic", "tract_pct": 28.0, "metro_pct": 11.7}, …], "baseline": "Unweighted mean across San Francisco tracts", "used_in_ranking": false}`. Only after the brief. The API never puts it in the case panel or chat. |
| R14 | Statutes say **why they apply** and **what is still needed**. | **Gap** | Add an optional `statute_notes: dict[str, {"applies_because": str, "needs": str}]` argument to `submit_brief`, copied into each `brief.statutes[]` entry. Example for `STAT-CA-01`: needs "an official citation on her unit left unabated more than 35 days". Until then the API shows built-in preconditions for the 3 CA statutes and computes "block case opened Nov 2 = 15 days → under 35". |
| R15 | Suggested next questions after each turn. | **Gap** | Add a tiny tool `suggest_next_questions(questions: list[str])` (2–4 short questions the paralegal is likely to ask next, in their words) that only stores to state; the API shows them as chips. Until then the API derives them from which steps are done. |

### Brief JSON (`submit_brief`)

| # | Requirement | Status | Change |
|---|---|---|---|
| R16 | `case` carries what the header and Brief print. | **Gap** | Add `case_id`, `client_initials`, `hearing_time` (HH:MM, optional), `notice_type`. Today the API keeps these from the intake form, so the brief still prints them. |
| R17 | `excluded` is always present, even empty. | Met | |
| R18 | `cannot_prove` includes the standard two lines plus case-specific ones. | Met | Keep "to close the gap: photos, texts, rent ledger, her own DBI complaint number" style lines in `extra_cannot_prove`. |
| R19 | `stub_tools` is honest. | Met | The UI shows an orange note on the header and the Brief while any tool is a stub. |
| R20 | `memo_markdown` uses Markdown headings and bold labels, under 350 words. | Met | Rendered with markdown-it + DOMPurify; record ids become chips. "Mark reviewed" is a UI state, not an agent call. |

### Safety, privacy and trust

| # | Requirement | Status |
|---|---|---|
| R21 | Initials and block only. The intake form converts any name to initials before the agent sees it; the agent must not ask for or repeat names or unit numbers. | Met (API) + prompt line recommended |
| R22 | `audit_*` data never before the brief, never in ranking, never in chat. | Met (code + `bq_mcp` guard). The API keeps `equity_audit` out of the panel. |
| R23 | Say "on the tenant's block", never "in her unit", for 311 evidence. Filing counts are always "modeled". | Met |
| R24 | The agent does not emit A2UI JSON. | By design. If a future feature needs agent-authored UI (for example a free-form checklist), use `a2ui-adk`'s `SendA2uiToClientToolset` on a **separate surface**, never for evidence, statutes or funds. |

### Runtime

| # | Requirement | Status |
|---|---|---|
| R25 | A full first turn finishes in about 40 s with a `status` event per tool call. | Met |
| R26 | Errors come back as `{"error": "..."}` tool results, not exceptions. | Met; the API turns any runner exception into an `error` event and ends the turn. |
| R27 | Cloud Run: `--min-instances=1 --max-instances=1` (in-memory ADK sessions and workspaces), timeout 3600, service account with BigQuery Job User, BigQuery Data Viewer, Vertex AI User. | Sid |

---

## 3. A2UI actions that become agent turns

These buttons live in A2UI surfaces. The API turns their `action` messages into chat text (echoed into the transcript) or handles them without the agent.

| Action (`action.name`) | From | Becomes |
|---|---|---|
| `ask` `{text}` | Suggested-question chips, memo **Regenerate** | `text`, verbatim |
| `explain_exclusion` `{request_id}` | **Ask why** on an excluded record | "Why did you exclude {id}? It looked similar to her conditions." |
| `submit_intake` `{client, block, issue, hearing, notice, household, ami}` | New-intake form | New case, then "New intake. {issue}. Are there open residential complaints on this block?" with the `[Intake facts]` prefix |
| `open_case` `{case_id}` | Queue | No agent call: switches case and ADK session |
| `focus_record` `{request_id}` | Citation chip in chat | No agent call: opens the tab and highlights the card |
| `mark_memo_reviewed` | Memo tab | No agent call |

---

## 4. Acceptance checks (run against the live agent)

Run them in the UI with `A4I_AGENT_MODE=live`, or in `adk web` for the agent-only ones.

1. *"Tenant on the 600 block of John Muir Dr, water under the floorboards outside her 4th-floor unit, mold, heater barely works. Hearing Monday 9 AM. Household of 3, income unknown."* → Evidence lists `SF-202665044` as **Same block**; no `DECOY-*` id in Evidence; the excluded drawer shows each decoy with its failing field; header shows tract `06075033204`.
2. Click **Ask why** on `DECOY-SANF-02` → the reply names *commercial property* and does not cite it as evidence.
3. *"Which fund fits before Monday?"* with income unknown → Funds tab shows Prop F as **Likely fit** and ERAP as **Needs income** (R11), not an empty tab.
4. *"How bad is eviction pressure here?"* → Tract tiles show 30.3% vs 17.5% and filings with the violet **modeled** tag.
5. *"Draft the intake memo"* → Memo tab fills, the **Open Tenant Stabilization Brief** button enables, the Brief prints evidence, statutes (with **Needs:** lines), funds, tract, equity audit labelled "not used in ranking", and what the record cannot prove.
6. *"Actually it's the 700 block."* → new search, changed cards marked **Updated**, brief resubmitted (R5).
7. Hearing set to tomorrow → reply and memo lead with same-day steps (R6).
8. No reply, memo or panel ever contains a full name, a unit number, or an `audit_*` share outside the Brief's equity section.

Demo mode (`A4I_AGENT_MODE=mock`) replays checks 1–5 from `api/fixtures/demo_int_1142.json` (real 311, statute, fund and tract rows from `data/`; similarity scores are fixed replay values). `python -m pytest api/tests` asserts them.
