# sql/ — BigQuery embeddings, search, and analysis

**Owner:** Prachi · **Branch:** `data` · **Contract:** [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md#embedding-tables-prachi)

Every query the agent runs starts life here as a tested `.sql` file. Karthik wraps them in tools.

## Planned files

| File | What it does | Needed by |
|---|---|---|
| `01_embed_complaints.sql` | Builds `a4i_housing.complaints_embedded` | T+1:30 |
| `02_embed_statutes.sql` | Builds `a4i_housing.statutes_embedded` | T+1:30 |
| `03_embed_bulletins.sql` | Builds `a4i_housing.bulletins_embedded` | T+1:30 |
| `10_search_complaints.sql` | `VECTOR_SEARCH` + decoy labeling, parameter `@query` | T+1:30 |
| `11_decoy_check.sql` | Shows raw top hits for "no heat" / "black mold", then shows all 9 decoys excluded | T+1:30 (also a deck screenshot) |
| `20_tract_summary.sql` | 4 quarters summed per tract **before** joining to ACS | T+1:30 |
| `30_equity_audit.sql` | `audit_*` shares + silent-distress tracts vs. metro baseline | T+3:00 |

## Before you run anything

- The Vertex connection `us.a4i-vertex` must exist (Sid, T+0:30). Check with `bq show --connection qwiklabs-gcp-04-3b4b41069fc3.us.a4i-vertex`.
- `AI.EMBED` returns a struct. Keep `.result` and drop rows where `status != ''`.
- 174 rows is too small for a vector index. Use `options => '{"use_brute_force": true}'`.
- `top_k` applies **before** your `WHERE`. Use 20 or more, then filter.
- Keep `census_tract_geoid` as a string. SF's `06` prefix vanishes if it's cast to a number.
