# Architecture

**One WebSocket API → one ADK root agent → a few tools → BigQuery.** The UI only ever talks to the API. Only the tools touch BigQuery.

```
 Browser UI ──WebSocket /ws──► API (FastAPI, Cloud Run)
                                    │  one ADK Runner per server,
                                    │  one ADK session per conversation
                                    ▼
                        Root agent "navigator" (Gemini)
     ┌──────────────────┬───────────────┬────────────────┬────────────────┐
     ▼                  ▼               ▼                ▼                ▼
 semantic_search    match_fund     tract_context    equity_audit     BigQuery MCP
 (custom, vector)   (custom, rules) (custom, SQL)    (custom, SQL)    (Google-managed)
     │
     ▼
 a4i_housing.complaints_embedded / statutes_embedded / bulletins_embedded
```

## Design decisions

| Decision | Why |
|---|---|
| **One root agent, not many** | Fewer prompts to debug and less latency during a live demo. A second agent (311 request drafter) is a stretch goal only. |
| **WebSocket API in front** | One URL and one event format for the UI. Tool progress streams live, which looks good in the video. |
| **Vector search is one tool for all three corpora** | `semantic_search(query, corpus)`: one function to test. The decoy filter lives *inside* the tool, so decoys never reach the LLM unlabeled. |
| **Fund eligibility is plain Python** | AMI caps and open-case rules are legal criteria. Code decides, the LLM explains. |
| **BigQuery MCP for ad-hoc lookups** | Meets the "consume a Google-managed MCP server" requirement and lets the agent answer questions our tools don't cover. |
| **`max-instances=1` on Cloud Run** | ADK's in-memory sessions don't survive a reconnect to a different instance. One instance is fine for a demo. |

## Tools

| Tool | Owner | Input | Returns |
|---|---|---|---|
| `semantic_search` | Karthik (SQL from Prachi) | `query: str`, `corpus: "complaints" \| "statutes" \| "funds"`, `block_address?: str`, `top_k=20` | `matches[]` and, for complaints, `excluded[]` with a reason each |
| `match_fund` | Karthik | `income_pct_ami: float`, `household_size: int`, `has_open_habitability_case: bool`, `is_residential: bool` | Each of the 4 SF funds: `eligible`, `why`, `intake_url` |
| `tract_context` | Karthik (SQL from Prachi) | `census_tract_geoid: str` (keep as **string**, 11 chars) | Severe rent burden %, annual modeled filings (summed over 4 quarters), metro comparison |
| `equity_audit` | Prachi | `census_tract_geoids: list[str]` | `audit_*` shares vs. metro baseline. **Runs after the brief, never feeds ranking.** |
| BigQuery MCP | Sid | — | Managed tools for table lookups and ad-hoc SQL |

### Decoy filter (inside `semantic_search`, complaints only)

Vector search runs first with `top_k` 20 or more, using `{"use_brute_force": true}` (no index on 174 rows). Then every hit is labeled:

| Condition | Result |
|---|---|
| `property_type != 'Residential'` | excluded: "Commercial property" |
| `inspection_status = 'Closed - No Violation'` | excluded: "Inspector found no violation" |
| `closed_date IS NOT NULL` | excluded: "Closed — `<inspection_status>`" |
| otherwise | **match** |

Check the commercial rule before the closed rule: the 3 commercial decoys are still **open**.

### Fund rules (San Francisco)

| Fund | Income cap | Needs open habitability case |
|---|---|---|
| SF Emergency Rental Assistance (ERAP) | ≤ 80% AMI (priority ≤ 30%) | No |
| MEDA Family Stabilization Grant | ≤ 60% AMI | No |
| DBI Relocation & Mold Remediation Bridge | not stated | Yes (open, un-abated DBI notice) |
| Prop F Right to Counsel & Habitability Defense | not stated | Yes (open DBI complaint) |

The caps come from `raw_bulletin_text`. Prachi confirms them against the table. All four are residential-only.

## WebSocket contract

**Endpoint:** `wss://<cloud-run-url>/ws`. Every message is one JSON object with a `type`.

### Client → server

```json
{ "type": "user_message", "session_id": "abc123", "text": "Tenant on the 400 block of Eddy St, no heat for 2 weeks, mold, hearing Monday" }
```

The client makes up `session_id` (a random string) and reuses it for the whole conversation.

### Server → client

| `type` | When | Shape |
|---|---|---|
| `status` | A tool starts | `{ "type": "status", "tool": "semantic_search", "text": "Searching 311 records…" }` |
| `message` | Agent text, may arrive in chunks | `{ "type": "message", "text": "…", "final": false }` |
| `brief` | The brief is ready or updated | `{ "type": "brief", "brief": { …see below… } }` |
| `error` | Something failed | `{ "type": "error", "text": "…" }` |

### Brief JSON (draft — Sid owns the final version)

Selvan builds the card from this shape. Karthik's agent produces it.

```json
{
  "case": {
    "block_address": "400 Block Eddy St, San Francisco, CA",
    "hazards": ["no heat", "mold"],
    "hearing_date": "2026-11-23",
    "household_size": 3,
    "income_pct_ami": 45
  },
  "evidence": [
    { "request_id": "…", "block_address": "…", "raw_complaint_type": "…",
      "inspection_status": "Open - Active DBI Case", "created_date": "2026-10-02",
      "similarity": 0.82, "narrative": "…" }
  ],
  "excluded": [
    { "request_id": "DECOY-SANF-01", "reason": "Commercial property", "similarity": 0.88 }
  ],
  "statutes": [
    { "code_citation": "Cal. Civ. Code § 1941.1 & § 1942.4", "ordinance_title": "…", "protection": "…" }
  ],
  "funds": [
    { "program_name": "…", "administering_agency": "…", "eligible": true,
      "why": "45% AMI ≤ 80% cap; residential", "requires_open_habitability_case": false,
      "intake_url": "https://sf.gov/renthelp" }
  ],
  "tract_context": {
    "census_tract_geoid": "06075012400",
    "severe_rent_burden_pct": 24.1,
    "metro_severe_rent_burden_pct": 17.5,
    "annual_filings_modeled": 88
  },
  "equity_note": "…",
  "cannot_prove": [
    "311 records show conditions on the block, not inside this tenant's unit",
    "Eviction filing counts are modeled neighborhood baselines, not court dockets"
  ],
  "memo_markdown": "## Intake memo\n…"
}
```

`similarity` = `1 - cosine_distance`. `excluded` is always included, even when empty. That's the decoy-catching evidence judges look for.

## Deploy (Sid)

- Cloud Run: `--min-instances=1 --max-instances=1 --timeout=3600`, region `us-central1`.
- Service account needs `roles/bigquery.user`, `roles/bigquery.dataViewer`, and `roles/aiplatform.user`.
- BigQuery connection `us.a4i-vertex` (CLOUD_RESOURCE) with `roles/aiplatform.user`, as in Section 13 of the notebook.
- **Fallback if WebSockets misbehave:** ADK's built-in `api_server` streams over SSE (`/run_sse`). The API keeps the same event types, so the UI barely changes.

## Embedding tables (Prachi)

| Table | Embedded text | Source |
|---|---|---|
| `complaints_embedded` | `complaint_narrative` | `municipal_311_housing_complaints` |
| `statutes_embedded` | `ordinance_title` + `raw_statute_text` | `municipal_housing_ordinance_statutes` |
| `bulletins_embedded` | `program_name` + `raw_bulletin_text` | `rental_relief_program_bulletins` |

All use `AI.EMBED(…, connection_id => 'us.a4i-vertex', endpoint => 'gemini-embedding-2')`. Keep `.result` and drop rows where `status != ''`. Never embed `audit_*` columns.
