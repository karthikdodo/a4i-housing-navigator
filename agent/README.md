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

---

## Sid's prototype: `housing_navigator` (agent_101 branch)

A separate, working ADK agent built in parallel with `navigator`. Its tract context, equity audit and fund-eligibility logic are candidates for filling the `navigator` stubs. The `adk deploy` script and Cloud Console steps below also apply to `navigator` (use `agent/navigator` as the path).

```
agent/
  housing_navigator/
    agent.py        ADK root agent, instructions, BigQuery MCP toolset
    tools.py        custom domain tools (vector search + eligibility post-filter)
    bq.py, config.py
    requirements.txt, .env.example
  setup_embeddings.sql   one-time AI.EMBED materialization (complaints, statutes, bulletins)
  deploy.sh              adk deploy cloud_run (--min-instances=1, with web UI)
```

#### Custom tools

| Tool | What it does |
|---|---|
| `search_habitability_evidence` | `AI.EMBED` + `VECTOR_SEARCH` (top_k 20, brute force) over 311 narratives, then a hard post-filter (`Residential` and `closed_date IS NULL`). Returns accepted evidence **and** rejected near-misses with reasons, flagging `DECOY-*` rows and any rejected row that outranked the accepted ones. |
| `locate_block` | Street or 100-block → census tract GEOID(s), kept as strings |
| `match_statutes` | Vector search over embedded statute text for the state |
| `check_relief_eligibility` | Vector search over relief bulletins, then hard rules `requires_open_habitability_case` / `residential_tenants_only`. Ineligible programs are returned with the reason. |
| `get_tract_context` | ACS and filings **pre-aggregated per tract** (no 4x join inflation), with metro percentiles and real-vs-modeled caveats |
| `find_silent_distress_tracts` | Equity audit: high filing pressure and rent burden with few open 311s. `audit_*` shares are reported but never scored. |

The Google-managed **BigQuery MCP server** (`https://bigquery.googleapis.com/mcp`) is attached as a toolset for ad-hoc schema and count questions. It is disabled with `ENABLE_BQ_MCP=false`.

#### Team setup: run it from the Google Cloud Console

Everything below runs in **Cloud Shell**, so you don't need a local install. Team project: `qwiklabs-gcp-04-3b4b41069fc3`.

**1. Open Cloud Shell in the team project**
1. Go to https://console.cloud.google.com and sign in with your Qwiklabs student account.
2. In the project picker at the top, choose `qwiklabs-gcp-04-3b4b41069fc3`.
3. Click the **Activate Cloud Shell** icon (`>_`) at the top right.

**2. Get the code**
```bash
gcloud config set project qwiklabs-gcp-04-3b4b41069fc3
git clone https://github.com/karthikdodo/a4i-housing-navigator.git
cd a4i-housing-navigator && git checkout agent_101
python3 -m venv .venv && .venv/bin/pip install -q -r agent/housing_navigator/requirements.txt
cp agent/housing_navigator/.env.example agent/housing_navigator/.env
sed -i "s/your-qwiklabs-project-id/$(gcloud config get-value project)/" agent/housing_navigator/.env
```

**3. Try it in the browser from Cloud Shell (dev mode, only you can see it)**
```bash
.venv/bin/adk web agent --port 8080
```
Click **Web Preview** (the eye icon in the Cloud Shell toolbar), then **Preview on port 8080**, then choose `housing_navigator` in the dropdown at the top left. Paste the demo intake below. Press `Ctrl+C` to stop.

**4. Deploy to Cloud Run (a shared URL for the team and judges). One person does this.**
```bash
PATH="$PWD/.venv/bin:$PATH" ./agent/deploy.sh
```
The build takes about 5 minutes. At the end it prints a `Service URL`. Open it in any browser and choose `housing_navigator`. You can also find the URL in **Console → Cloud Run → housing-navigator**.
To redeploy after code changes, `git pull` and run the same command again.

**Already done for this project (don't repeat):**
- 311 complaints are embedded in `a4i_housing.complaint_embeddings`, and statutes and bulletins in `statutes_embedded` and `bulletins_embedded`. All use `text-embedding-005`, so no Vertex connection is needed. To rebuild: `bq query --use_legacy_sql=false --location=US < agent/setup_embeddings.sql`
- The default compute service account `973935346020-compute@developer.gserviceaccount.com` has these roles: `bigquery.jobUser`, `bigquery.dataViewer`, `aiplatform.user`, `mcp.toolUser`, `storage.objectViewer`, `artifactregistry.writer`, `logging.logWriter`.

**Troubleshooting**
| Symptom | Fix |
|---|---|
| `Permission denied` on BigQuery or Vertex in Cloud Run | Check the roles above under **IAM & Admin → IAM** |
| The agent fails on `bq_mcp_*` tools | Set `ENABLE_BQ_MCP=false` in `deploy.sh` and redeploy. The core tools don't need MCP. |
| `RATE_LIMIT_EXCEEDED` from gcloud | Add `--billing-project=qwiklabs-gcp-04-3b4b41069fc3` to the command |
| Errors or logs | **Console → Cloud Run → housing-navigator → Logs** |

#### Demo script (decoy resilience)
> "Tenant on the 400 block of Lake St. Radiators have been cold for two weeks since the boiler failed and water from upstairs is dripping near the kitchen fuse box. 3-day notice, nonpayment hearing Monday 9am. Family of 3, about $4,200 behind."

Then: *"Why did you exclude the commercial mold complaint?"* → *"Which funds need an open habitability case?"* → *"Who are we missing if we require an open 311 ticket?"* → *"Draft the memo."*
