# Tenant Stabilization Navigator — San Francisco

**Agents for Impact 2026 · Affordable Housing Stability & Eviction Prevention**

A legal-aid paralegal chats with our agent about a tenant facing a nonpayment hearing. The agent finds **open residential 311 habitability complaints on the tenant's block** using BigQuery Vector Search, throws out decoys (commercial, closed, no-violation), matches the **statute** and an **eligible emergency fund**, and drafts a **Tenant Stabilization Brief** plus a legal-aid intake memo.

| | |
|---|---|
| **Metro** | San Francisco, CA |
| **Track** | 1 — Today at intake, with Track 2 fund matching built in |
| **User** | Right-to-counsel paralegal, tenant has a Monday hearing |
| **Stack** | ADK (Python) + Gemini · BigQuery `AI.EMBED` + `VECTOR_SEARCH` · BigQuery MCP · Cloud Run |
| **GCP project** | `qwiklabs-gcp-04-3b4b41069fc3`, dataset `a4i_housing` (loaded) |

> New here? Read in this order: this page → [`docs/TEAM_PLAN.md`](docs/TEAM_PLAN.md) (who does what, when) → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (how the parts talk) → the README in your own folder.
> The original challenge brief is in [`docs/CHALLENGE.md`](docs/CHALLENGE.md).
> **Running the app, who it is for, and diagrams of the A2UI workspace:** [`docs/A2UI_ARCHITECTURE.md`](docs/A2UI_ARCHITECTURE.md). Quick start: `./start.sh` (demo) or `./start.sh live`, then open http://localhost:5173; `./stop.sh` to stop.

---

## How it fits together

```
 UI (ui/) ──WebSocket──► API (api/, FastAPI on Cloud Run)
                               │
                               ▼
                     ADK root agent (agent/, Gemini)
          ┌──────────────┬─────────┴───────┬──────────────┐
          ▼              ▼                 ▼              ▼
   semantic_search   match_fund     tract_context    BigQuery MCP
   (vector + decoy   (rules, no     (4-quarter-safe  (Google-managed,
    filter)           LLM)           SQL)             required)
          │
          ▼
   BigQuery a4i_housing: *_embedded tables built by sql/
```

One API, one agent, a handful of tools. Details and the JSON contract: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Who owns what

| Folder | Owner | What lives there | Branch |
|---|---|---|---|
| [`api/`](api/) | Karthik (with Sid) | FastAPI WebSocket server that runs the agent | `agent` |
| [`agent/`](agent/) | Karthik | ADK root agent, system prompt, tools | `agent` |
| [`sql/`](sql/) | Prachi | Embedding tables, vector search, tract summary, equity audit | `data` |
| [`ui/`](ui/) | Selvan | Chat + Stabilization Brief card | `ui` |
| [`infra/`](infra/) | Sid | Vertex connection, Dockerfile, Cloud Run deploy | `infra` |
| [`docs/`](docs/) | April | Plan, architecture, deck notes, provenance & limitations | `story` |
| `data/`, `notebooks/`, `scripts/` | — | Organizer starter kit. **Don't edit.** | — |

## Getting started (everyone)

```bash
git clone https://github.com/karthikdodo/a4i-housing-navigator.git
cd a4i-housing-navigator
git checkout -b <your-branch>        # agent | data | ui | infra | story

# Point gcloud at the lab project. Use a separate config if your machine has other accounts.
gcloud config configurations create a4i     # first time only
gcloud auth login                           # the student_..@qwiklabs.net lab account
gcloud auth application-default login       # lets Python code reach BigQuery
gcloud config set project qwiklabs-gcp-04-3b4b41069fc3

cp .env.example .env                        # then fill in the agent values
```

Check you can see the data:

```bash
bq query --use_legacy_sql=false \
  'SELECT COUNT(*) AS complaints FROM a4i_housing.municipal_311_housing_complaints'
# expect 174 (165 real + 9 DECOY-*)
```

The data is **already loaded** for San Francisco. Don't re-run `scripts/load.sh` unless the team agrees: everyone shares one project.

## Team rules

1. **Shared project.** Never drop, rename, or overwrite a table in `a4i_housing` without saying so in team chat.
2. **Branch per lane.** Merge to `main` only when another lane needs your work. Small PRs, quick reviews.
3. **No secrets in git.** `.env`, keys, and service-account JSON are git-ignored. Keep it that way.
4. **`audit_*` columns** never go into search, scoring, or prompts. They're used only in the post-output equity audit.
5. **Eviction filings are 4 rows per tract.** Aggregate by `census_tract_geoid` before any join.
6. **Say what the data can't prove.** 311 records show block conditions, not the tenant's unit. Eviction counts are modeled.

## Data at a glance

| Table | Rows (SF) | Real or modeled |
|---|---:|---|
| `municipal_311_housing_complaints` | 174 | Real 311 records (100-block) + 9 planted `DECOY-*` rows |
| `acs_tract_housing_tenure` | 42 | Real US Census ACS |
| `court_eviction_filings` | 168 (4 per tract) | **Modeled** |
| `rental_relief_program_bulletins` | 4 | Public policy text |
| `municipal_housing_ordinance_statutes` | 3 | Public statute text |

Full provenance: [`data/README.md`](data/README.md).

## Submission checklist (April)

- [ ] Public GitHub repo link
- [ ] Google Skills project link with the agent live on Cloud Run
- [ ] Pitch deck: problem, metro & track, architecture, data provenance, equity audit numbers, limitations
- [ ] Pitch video, 3 minutes max, live end-to-end run on the deployed app

## License

Starter kit © the A4I 2026 organizers, Apache 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
