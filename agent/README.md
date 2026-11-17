# agent/: ADK root agent and tools

**Owners:** Karthik (`agent.py`, `prompts.py`, `brief.py`, `bq_mcp.py`, `tools/semantic_search.py`) · Prachi (`tools/match_fund.py`, `tools/tract_context.py`, `tools/equity_audit.py`)
**Branches:** `agent-core` (Karthik), `agent-tools` (Prachi) · **Contract:** [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)

One ADK root agent (`navigator`) on Gemini. The WebSocket server in [`api/`](../api/) imports `root_agent` and runs it.

## Run it

```bash
# once
python3 -m venv .venv && .venv/bin/pip install -r agent/requirements.txt
gcloud auth application-default login        # the student-…@qwiklabs.net lab account

# chat with it in the browser (from the repo root)
.venv/bin/adk web agent/                     # open http://localhost:8000, pick "navigator"
```

**Testing from the Google Cloud Console (Cloud Shell, no local install):** see [`docs/TESTING_IN_CLOUD_CONSOLE.md`](../docs/TESTING_IN_CLOUD_CONSOLE.md).

No `.env` needed: defaults in [`navigator/config.py`](navigator/config.py) point at the lab project. Override with env vars (`A4I_MODEL`, `A4I_ENABLE_BQ_MCP=false`, …).

Try: *"Tenant on the 100 block of Turk St, no heat for two weeks and black mold. Hearing 2026-11-23. Household of 3, 45% AMI."* Then ask *"Why didn't you use DECOY-SANF-05?"*

## Layout

```
agent/navigator/
  agent.py           root_agent, tool list, TOOL_STATUS_TEXT for the UI
  prompts.py         system prompt: workflow, evidence rules, memo format
  brief.py           submit_brief / add_equity_note + after-tool callback that records tool results
  bq_mcp.py          Google-managed BigQuery MCP server (read-only tools) + audit_* guard
  config.py          project, dataset, model, embedding endpoint, table names
  tools/
    resolve_date.py      "tomorrow" / "next Monday" / "Nov 23" → exact date (flags ambiguous ones)
    semantic_search.py   AI.EMBED + VECTOR_SEARCH (live BigQuery) + decoy filter
    _stubs.py            placeholders for Prachi's tools; auto-replaced when her files exist
    __init__.py          picks the real tool if its file exists, else the stub
```

## How it works

1. `semantic_search` runs real BigQuery Vector Search (`text-embedding-005`, cosine, brute force) over Sid's `complaint_embeddings`, `statutes_embedded`, `bulletins_embedded`. For complaints it runs a second search limited to the tenant's block, so on-block cases always surface, flagged `on_tenant_block`.
2. Every complaint hit goes through the decoy filter in code (commercial → no violation → closed). Hits come back as `matches` or `excluded` with a reason.
3. An `after_tool_callback` stores every tool result in session state.
4. `submit_brief` builds the brief JSON **from those stored rows by ID**. It rejects excluded or unknown IDs, so the model can't cite a decoy or make up a record.

## For April (api/)

- Import: `from navigator.agent import root_agent, TOOL_STATUS_TEXT` (add `agent/` to `PYTHONPATH`).
- Run with `runner.run_async(..., run_config=RunConfig(streaming_mode=StreamingMode.SSE))` (`from google.adk.agents.run_config import RunConfig, StreamingMode`) so text arrives in chunks: `event.partial == True` → `{"type": "message", "text": chunk, "final": false}`; the non-partial text event → `"final": true`.
- With SSE on, every function call arrives **twice** (partial + final). Handle `function_call` / `function_response` only when `event.partial` is falsy, or the UI shows each step twice.
- A full case takes ~40 s (about 7 model steps). Send a `status` event per step so the UI never looks frozen.
- `status` event: on each `function_call`, send `{"type": "status", "tool": name, "text": TOOL_STATUS_TEXT.get(name, "Working…")}`.
- `brief` event: on a `function_response` named `submit_brief` or `add_equity_note` whose `response["status"] == "ok"`, send `{"type": "brief", "brief": response["brief"]}`.
- The final brief is also in session state under `"brief"`.
- Deploy needs `mcp` installed (it's in `requirements.txt`) and a service account with BigQuery job user + data viewer and Vertex AI user.

## For Prachi (tools/)

Create `tools/match_fund.py`, `tools/tract_context.py`, `tools/equity_audit.py`, each with a function of the **same name and arguments** as in [`tools/_stubs.py`](navigator/tools/_stubs.py). No other edit needed; the registry picks yours up and the stub stops being used. Return shapes the brief reads:

- `match_fund` → `{"funds": [{program_name, administering_agency, eligible, why, requires_open_habitability_case, intake_url}]}`
- `tract_context` → `{census_tract_geoid, severe_rent_burden_pct, metro_severe_rent_burden_pct, annual_filings_modeled}` (sum the 4 quarters)
- `equity_audit` → anything JSON; the agent summarizes it into `equity_note`.

Write docstrings with an `Args:` section; Gemini reads them to decide how to call the tool.

## Rules the system prompt enforces

- A 311 match corroborates **block** conditions (`block_address`), never a specific apartment.
- Eviction filing counts are **modeled** neighborhood baselines, not this tenant's court record.
- Never cite an excluded (decoy) record as evidence. Say why it was excluded if asked.
- Fund eligibility comes from `match_fund`, not the model's own judgment.
- `audit_*` columns never appear before the brief is written (also enforced in code for MCP SQL).

---

## Organizer requirements (from the original template)

- **An ADK agent**, in Python. ✅
- **At least one tool you built yourself.** ✅ `semantic_search`, `submit_brief`, Prachi's tools.
- **At least one Google-managed MCP server, consumed.** ✅ BigQuery MCP (`https://bigquery.googleapis.com/mcp`).
- **Deployed to Google Cloud**, on Agent Runtime or Cloud Run. ⏳ April.
- **Required differentiator: BigQuery Vector Search.** ✅ `AI.EMBED` + `VECTOR_SEARCH` on every search.

> Vector search is a **candidate generator, not an answer**. Every metro has nine planted near-miss decoys (`DECOY-*`). What you do *after* the search is what makes the agent useful.
