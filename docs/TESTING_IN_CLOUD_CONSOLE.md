# Testing the navigator agent in the Google Cloud Console

These steps run the `navigator` agent from your browser through **Cloud Shell**, so you don't need a local install. They take about 5 minutes.

Team project: `qwiklabs-gcp-04-3b4b41069fc3` · Branch: `_sidd_agent_101`, or `main` once the PR is merged

## 1. Open Cloud Shell in the team project

1. Go to <https://console.cloud.google.com> and sign in with your **Qwiklabs student account** (`student-…@qwiklabs.net`), not your personal Google account.
2. In the project picker at the top, choose `qwiklabs-gcp-04-3b4b41069fc3`.
3. Click **Activate Cloud Shell** (the `>_` icon, top right). A terminal opens at the bottom of the page.

## 2. Get the code

```bash
gcloud config set project qwiklabs-gcp-04-3b4b41069fc3
cd ~
git clone -b _sidd_agent_101 https://github.com/karthikdodo/a4i-housing-navigator.git navigator-test
cd navigator-test
git branch --show-current            # should print _sidd_agent_101
ls agent/navigator/tools             # should list locate_block.py and semantic_search.py
```

> **Already have a clone?** Run `git fetch origin && git checkout -b _sidd_agent_101 origin/_sidd_agent_101` inside it.
> If you get `pathspec '_sidd_agent_101' did not match`, run `git remote -v`. It must point to `karthikdodo/a4i-housing-navigator`.

## 3. Install

```bash
python3 -m venv .venv
.venv/bin/pip install -q -r agent/requirements.txt
```

You don't need a `.env` file or `gcloud auth application-default login`. Cloud Shell already uses your Qwiklabs credentials, and `agent/navigator/config.py` points at the team project by default.

## 4. Quick check: run the tools without the LLM (about 10 seconds)

This tests BigQuery access and `locate_block` without involving Gemini:

```bash
PYTHONPATH=agent A4I_ENABLE_BQ_MCP=false .venv/bin/python -c "
from navigator.tools import locate_block, semantic_search
for a in ['400 block of Lake St', '3600 Block 18th St', '300 Ellis St', 'Guerrero St', '999 Nowhere Blvd']:
    r = locate_block(a)
    print(f'{a:22} ->', r.get('census_tract_geoid'), r.get('match'), r.get('blocks_away'), r.get('error', ''))
r = semantic_search('black mold and sewage backup')
print('vector search:', len(r['matches']), 'matches,', len(r['excluded']), 'excluded:', [e['request_id'] for e in r['excluded'][:3]])
"
```

Expected:

```
400 block of Lake St   -> 06075045100 exact_block 0
3600 Block 18th St     -> 06075020300 exact_block 0
300 Ellis St           -> 06075012202 nearest_block_same_street 3
Guerrero St            -> 06075020300 street_only None
999 Nowhere Blvd       -> None None None No 311 records on a street matching 'nowhere' ...
vector search: ... matches, ... excluded: ['DECOY-SANF-02', 'DECOY-SANF-05', ...]
```

A line like `tools/match_fund.py not found, using STUB` is expected until Prachi's tools are merged.

## 5. Chat with the agent in the browser

```bash
.venv/bin/adk web agent --port 8080 --allow_origins "regex:https://.*\.cloudshell\.dev"
```

1. Wait for `Uvicorn running on http://127.0.0.1:8080`.
2. In the Cloud Shell toolbar, click **Web Preview** (the eye icon), then **Preview on port 8080**. A new tab opens.
3. In the dropdown at the top left, choose **navigator**.
4. Paste a prompt from the next section.
5. The left panel shows every tool call with its exact input and output, which is useful for checking `locate_block`.

Press `Ctrl+C` in Cloud Shell to stop. Start a **New Session** in the UI for each new case.

> **Blank page?** You probably left out `--allow_origins`. Stop the server, rerun the command above, and open a *new* Web Preview tab.
> **Agent missing from the dropdown?** Run `curl -s localhost:8080/list-apps` in a second Cloud Shell tab. It should print `["navigator"]`. If it prints `[]`, you started `adk web` outside the repo root.

## 6. Prompts to test

Give an explicit hearing date, household size and % AMI. Otherwise the agent stops and asks for them, which is intended behavior.

**A. On-block evidence (main demo).** The tract comes from `semantic_search`, so `locate_block` shouldn't be needed.
> Tenant on the 400 block of Lake St. Radiators cold for two weeks since the boiler failed, water dripping near the kitchen fuse box. Nonpayment hearing 2026-11-23. Household of 3, 45% AMI, residential.

Expect: on-block case `SF-202665077`, decoys listed as excluded, Cal. Civ. Code § 1941.1/1942.4.

**B. No on-block case (tests `locate_block`).**
> Tenant at 300 Ellis St, black mold in the bathroom and no heat for a week. Hearing 2026-11-23. Household of 2, 40% AMI, residential.

Expect, in the left panel:
- `semantic_search` returns `on_block_match_count: 0`.
- `locate_block("300 Ellis St")` returns `06075012202` with `nearest_block_same_street` and `blocks_away: 3`.
- `tract_context` is then called with `06075012202`.
- The memo calls the tract **approximate** and doesn't cite any `locate_block` record as evidence.

**C. Street not in the data (tests the error path).**
> Tenant at 999 Nowhere Blvd, no heat. Hearing 2026-11-23. Household of 4, 30% AMI, residential.

Expect: `locate_block` returns an error. The agent should then ask for the tract or a cross street, or skip the equity audit, and never invent a tract.

**D. Decoy resilience.** Ask this after A, in the same session:
> Why didn't you use DECOY-SANF-05? Also search black mold and sewage backup.

**E. Equity audit.** Ask this after a brief exists:
> Who are we missing if relief requires an open 311 ticket?

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `403` / `Access Denied` on BigQuery | You're signed in with the wrong account. Run `gcloud auth list`; the active account must be `student-…@qwiklabs.net`. |
| `Project ... not found` | `gcloud config set project qwiklabs-gcp-04-3b4b41069fc3` |
| `bq_mcp` / MCP errors | Start with `A4I_ENABLE_BQ_MCP=false .venv/bin/adk web ...`. The core tools don't need MCP. |
| `RATE_LIMIT_EXCEEDED` from gcloud | Add `--billing-project=qwiklabs-gcp-04-3b4b41069fc3` to the gcloud command |
| `ModuleNotFoundError: mcp` | `.venv/bin/pip install -r agent/requirements.txt` |
| Web Preview port in use | Use `--port 8081`, then **Web Preview → Change port → 8081** |

## 8. Optional: share a URL with Cloud Run

Cloud Shell Web Preview is visible only to you. For a quick shared preview of the ADK UI (not the final WebSocket API and UI deploy in `infra/`), run:

```bash
PROJECT_ID=qwiklabs-gcp-04-3b4b41069fc3
.venv/bin/adk deploy cloud_run --project $PROJECT_ID --region us-central1 \
  --service_name navigator-preview --with_ui agent/navigator \
  -- --min-instances=1 --allow-unauthenticated
```

The Cloud Run service account already has BigQuery, Vertex AI and MCP roles. The command prints a `Service URL`, which you can also find under **Console → Cloud Run → navigator-preview**. Logs are under **Cloud Run → navigator-preview → Logs**.

`--allow-unauthenticated` means anyone with the link can use the agent and spend the project's Gemini quota. Delete the service after the demo with `gcloud run services delete navigator-preview --region us-central1`.
