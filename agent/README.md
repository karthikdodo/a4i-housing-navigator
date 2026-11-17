# Your agent goes here

This folder is empty on purpose.

We built the on-ramp: real American Community Survey housing tenure counts, 100-block municipal 311 complaint narratives across six metros, modeled quarterly eviction baselines, public statutes and emergency rental relief bulletins, and a validation suite that tells you plainly whether any of it is wrong. We did not build the vehicle. The design decisions in your agent are what you will be judged on.

## What has to be true of what you build here

- **An ADK agent**, in Python.
- **At least one tool you built yourself.** A Python function tool or one you defined in MCP Toolbox both count. The obvious candidate wraps your semantic search query, while the more valuable one holds the logic that is not a single query: turning a tenant intake narrative into a targeted search string, enforcing residential and open-case eligibility rules, cross-checking statutory protections, and assembling the Tenant Stabilization Brief. Consuming only prebuilt generic tools and calling that your design does not count.
- **At least one Google-managed MCP server, consumed.** Do not author your own from scratch. Use BigQuery's built-in MCP server or the [MCP Toolbox for Databases](https://github.com/googleapis/mcp-toolbox).
- **Deployed to Google Cloud**, on Agent Runtime or Cloud Run (your choice).
- **Your required differentiator: BigQuery Vector Search.** Your agent must genuinely call semantic search (`AI.EMBED` + `VECTOR_SEARCH`) over complaint narratives or relief bulletins. Filtering on categories or `LIKE '%no heat%'` does not count, and it is the most common way a team misses the point while appearing to hit it.

## The thing worth remembering while you build

Vector search is a **candidate generator, not an answer**. Every metro in your corpus contains nine planted near-miss decoys (`DECOY-*`): commercial warehouses with broken heaters, closed historical mold repairs, and proactive clearance inspections that semantically resemble an active crisis. What you do *after* the search (enforcing `property_type = 'Residential'`, checking `closed_date IS NULL`, matching program rules in `rental_relief_program_bulletins`, and avoiding the 4x quarterly join inflation on `court_eviction_filings`) is where this agent becomes useful instead of merely clever.

See Section 13 of [`notebooks/c_housing_01_load_explore.ipynb`](../notebooks/c_housing_01_load_explore.ipynb) for the connection setup, query shape, and syntax rules.

---

## Our build: Tenant Stabilization Navigator (San Francisco, "Today at intake" track)

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

### Custom tools

| Tool | What it does |
|---|---|
| `search_habitability_evidence` | `AI.EMBED` + `VECTOR_SEARCH` (top_k 20, brute force) over 311 narratives, then a hard post-filter (`Residential` and `closed_date IS NULL`). Returns accepted evidence **and** rejected near-misses with reasons, flagging `DECOY-*` rows and any rejected row that outranked the accepted ones. |
| `locate_block` | Street or 100-block → census tract GEOID(s), kept as strings |
| `match_statutes` | Vector search over embedded statute text for the state |
| `check_relief_eligibility` | Vector search over relief bulletins, then hard rules `requires_open_habitability_case` / `residential_tenants_only`. Ineligible programs are returned with the reason. |
| `get_tract_context` | ACS and filings **pre-aggregated per tract** (no 4x join inflation), with metro percentiles and real-vs-modeled caveats |
| `find_silent_distress_tracts` | Equity audit: high filing pressure and rent burden with few open 311s. `audit_*` shares are reported but never scored. |

The Google-managed **BigQuery MCP server** (`https://bigquery.googleapis.com/mcp`) is attached as a toolset for ad-hoc schema and count questions. It is disabled with `ENABLE_BQ_MCP=false`.

### Team setup: run it from the Google Cloud Console

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

### Demo script (decoy resilience)
> "Tenant on the 400 block of Lake St. Radiators have been cold for two weeks since the boiler failed and water from upstairs is dripping near the kitchen fuse box. 3-day notice, nonpayment hearing Monday 9am. Family of 3, about $4,200 behind."

Then: *"Why did you exclude the commercial mold complaint?"* → *"Which funds need an open habitability case?"* → *"Who are we missing if we require an open 311 ticket?"* → *"Draft the memo."*
