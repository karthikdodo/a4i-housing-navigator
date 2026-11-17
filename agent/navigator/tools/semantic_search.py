"""semantic_search: BigQuery AI.EMBED + VECTOR_SEARCH, with the decoy filter applied in code.

Owner: Karthik. Embedding tables and SQL patterns: Sid (sql/).

Vector search only generates candidates. Every complaint hit is then labeled by plain
rules, so decoys (commercial, closed, no-violation) never reach the model unlabeled.
"""

import re
from typing import Optional

from google.cloud import bigquery

from .. import config

_client: Optional[bigquery.Client] = None


def _bq() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client(project=config.PROJECT, location=config.BQ_LOCATION)
    return _client


# corpus -> (table, SELECT list over `base`)
_CORPORA = {
    "complaints": (
        config.COMPLAINTS_TABLE,
        """base.request_id, base.block_address, base.census_tract_geoid, base.property_type,
           base.raw_complaint_type, base.inspection_status,
           CAST(base.created_date AS STRING) AS created_date,
           CAST(base.closed_date AS STRING) AS closed_date,
           base.complaint_narrative AS narrative, base.data_provenance""",
    ),
    "statutes": (
        config.STATUTES_TABLE,
        """base.statute_section_id, base.jurisdiction, base.code_citation, base.ordinance_title,
           base.raw_statute_text AS text, base.data_provenance""",
    ),
    "funds": (
        config.BULLETINS_TABLE,
        """base.bulletin_id, base.program_name, base.administering_agency, base.funding_stream,
           base.requires_open_habitability_case, base.residential_tenants_only,
           base.intake_url, base.raw_bulletin_text AS text, base.data_provenance""",
    ),
}


def block_pattern(block_address: str) -> Optional[str]:
    """'450 Eddy Street' / '400 block of Eddy St' -> '400 block eddy%' (LIKE on LOWER(block_address))."""
    m = re.search(
        r"(\d+)\s*(?:block\s+(?:of\s+)?)?([a-z0-9]+)", block_address.lower()
    )
    if not m:
        return None
    hundred = int(m.group(1)) // 100 * 100
    return f"{hundred} block {m.group(2)}%"


def exclusion_reason(row: dict) -> Optional[str]:
    """Decoy filter. Order matters: the 3 commercial decoys are still open."""
    if row.get("property_type") != "Residential":
        return "Commercial property"
    if row.get("inspection_status") == "Closed - No Violation":
        return "Inspector found no violation"
    if row.get("closed_date"):
        return f"Case closed ({row.get('inspection_status')}, {row['closed_date']})"
    return None


def _connection_arg() -> str:
    return f"connection_id => '{config.EMBED_CONNECTION}', " if config.EMBED_CONNECTION else ""


def _vector_search(corpus: str, query: str, top_k: int, block_like: Optional[str]) -> list[dict]:
    tbl, select = _CORPORA[corpus]
    where = "metro_area = @metro"
    params = [
        bigquery.ScalarQueryParameter("query", "STRING", query),
        bigquery.ScalarQueryParameter("metro", "STRING", config.METRO),
    ]
    if block_like:
        where += " AND LOWER(block_address) LIKE @block"
        params.append(bigquery.ScalarQueryParameter("block", "STRING", block_like))

    sql = f"""
    SELECT {select}, ROUND(1 - distance, 4) AS similarity
    FROM VECTOR_SEARCH(
      (SELECT * FROM {config.table(tbl)} WHERE {where}),
      'embedding',
      (SELECT AI.EMBED(@query, {_connection_arg()}endpoint => '{config.EMBED_ENDPOINT}').result AS query_vec),
      query_column_to_search => 'query_vec',
      top_k => {int(top_k)},
      distance_type => 'COSINE',
      options => '{{"use_brute_force": true}}'
    )
    ORDER BY distance
    """
    job = _bq().query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
    return [dict(r) for r in job.result()]


def semantic_search(
    query: str,
    corpus: str = "complaints",
    block_address: Optional[str] = None,
    top_k: int = 20,
) -> dict:
    """Semantic search over San Francisco housing records with BigQuery Vector Search.

    Args:
        query: Plain-language description, e.g. "no heat for two weeks, black mold in bathroom".
        corpus: "complaints" (311 habitability cases), "statutes" (habitability law),
            or "funds" (emergency rental relief programs).
        block_address: Tenant's block or street address, e.g. "400 block of Eddy St".
            Complaints only. Cases on that block are always searched and flagged.
        top_k: Candidates to pull before filtering. Keep at 20 or more for complaints.

    Returns:
        For complaints: `matches` (usable evidence) and `excluded` (decoys and closed or
        commercial cases, each with a reason). For statutes and funds: `matches` only.
    """
    if corpus not in _CORPORA:
        return {"error": f"Unknown corpus {corpus!r}. Use complaints, statutes, or funds."}
    try:
        if corpus != "complaints":
            rows = _vector_search(corpus, query, min(top_k, 10), None)
            return {"backend": "bigquery-vector-search", "corpus": corpus, "matches": rows}

        rows = _vector_search(corpus, query, max(top_k, 20), None)
        block_like = block_pattern(block_address) if block_address else None
        on_block_ids: set[str] = set()
        if block_like:
            block_rows = _vector_search(corpus, query, 10, block_like)
            on_block_ids = {r["request_id"] for r in block_rows}
            seen = {r["request_id"] for r in rows}
            rows += [r for r in block_rows if r["request_id"] not in seen]
    except Exception as e:  # surface to the model instead of crashing the run
        return {"error": f"BigQuery vector search failed: {e}"}

    matches, excluded = [], []
    for r in sorted(rows, key=lambda r: r["similarity"], reverse=True):
        r["on_tenant_block"] = r["request_id"] in on_block_ids
        r["planted_decoy"] = r["request_id"].startswith("DECOY-")
        if r.get("narrative") and len(r["narrative"]) > 600:
            r["narrative"] = r["narrative"][:600] + "…"
        reason = exclusion_reason(r)
        if reason:
            excluded.append({
                "request_id": r["request_id"],
                "reason": reason,
                "similarity": r["similarity"],
                "block_address": r["block_address"],
                "raw_complaint_type": r["raw_complaint_type"],
                "planted_decoy": r["planted_decoy"],
            })
        else:
            matches.append(r)

    return {
        "backend": "bigquery-vector-search",
        "corpus": "complaints",
        "block_filter": block_like,
        "on_block_match_count": sum(m["on_tenant_block"] for m in matches),
        "matches": matches,
        "excluded": excluded,
    }
