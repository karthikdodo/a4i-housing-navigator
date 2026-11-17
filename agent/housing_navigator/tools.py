"""Domain tools for the Tenant Stabilization Navigator.

Every tool here is custom: it wraps BigQuery Vector Search (AI.EMBED +
VECTOR_SEARCH) or tract statistics with the eligibility judgment a legal-aid
intake desk needs. Vector search only generates candidates. The hard
relational rules below decide what is evidence and what is rejected:

  * property_type must be 'Residential'
  * closed_date must be NULL (the case is still open)
  * rows whose provenance marks them as planted teaching decoys are labeled

Court filings come in 4 quarterly rows per tract, so they are always
aggregated per tract BEFORE any join (avoids 4x inflation).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from google.adk.tools import ToolContext

from . import bq, config
from .config import table

def _embed_expr(param: str) -> str:
    conn = f"connection_id => '{config.EMBED_CONNECTION}', " if config.EMBED_CONNECTION else ""
    return f"AI.EMBED({param}, {conn}endpoint => '{config.EMBED_ENDPOINT}').result"


def _rejection_reasons(row: dict[str, Any]) -> list[str]:
    reasons = []
    if row.get("property_type") != "Residential":
        reasons.append(
            f"property_type is '{row.get('property_type')}', so the complaint does not "
            "describe a residential tenancy and cannot corroborate a tenant habitability defense"
        )
    if row.get("closed_date"):
        reasons.append(
            f"case closed on {row['closed_date']} with status '{row.get('inspection_status')}', "
            "so there is no active, un-abated condition"
        )
    return reasons


def _is_planted(row: dict[str, Any]) -> bool:
    prov = (row.get("data_provenance") or "").lower()
    return "planted" in prov or str(row.get("request_id", "")).startswith("DECOY-")


def _street_key(text: str) -> str:
    """'400 block of Ellis St' -> 'ellis'. Used to flag same-street evidence."""
    t = text.lower()
    t = re.sub(r"\b\d+\s+block\b|\bblock of\b|\bblock\b|\bof\b", " ", t)
    t = re.sub(r"\b(st|street|ave|avenue|blvd|rd|road|way|dr|ct|pl|ter)\b\.?", " ", t)
    words = [w for w in re.findall(r"[a-z0-9']+", t) if len(w) > 2 and not w.isdigit()]
    return words[0] if words else ""


def search_habitability_evidence(
    intake_description: str,
    block_or_street: Optional[str] = None,
    census_tract_geoid: Optional[str] = None,
    top_k: int = 20,
    tool_context: Optional[ToolContext] = None,
) -> dict[str, Any]:
    """Semantic search of 311 housing complaints for evidence corroborating a tenant's hazard.

    Runs BigQuery VECTOR_SEARCH over embedded 311 complaint narratives for this
    metro, then applies hard eligibility filters. Returns accepted evidence
    (open residential cases) AND rejected near-misses with the reason each was
    excluded, so the paralegal can see why a semantically similar complaint
    did not make it into the brief.

    Args:
        intake_description: The tenant's hazard, rewritten as a concise search
            string in inspector vocabulary (e.g. "no heat radiators not working,
            water leaking onto electrical panel").
        block_or_street: Optional street or 100-block the tenant lives on
            (e.g. "400 block of Ellis St"). Matching evidence is flagged.
        census_tract_geoid: Optional 11-digit tract GEOID string (keep leading zero)
            to flag same-tract evidence.
        top_k: Number of nearest neighbours to pull before filtering (default 20;
            keep it high because filtering happens after top_k).

    Returns:
        dict with 'accepted_evidence', 'rejected_candidates', and a summary.
    """
    top_k = max(5, min(int(top_k or 20), 50))
    sql = f"""
    SELECT
      base.request_id, base.block_address, base.census_tract_geoid,
      base.property_type, base.raw_complaint_type, base.inspection_status,
      base.created_date, base.closed_date, base.data_provenance,
      base.complaint_narrative,
      ROUND(distance, 4) AS cosine_distance
    FROM VECTOR_SEARCH(
      (SELECT * FROM {table(config.COMPLAINTS_EMBEDDED_TABLE)} WHERE metro_area = @metro),
      'embedding',
      (SELECT {_embed_expr('@q')} AS query_vec),
      query_column_to_search => 'query_vec',
      top_k => @top_k,
      distance_type => 'COSINE',
      options => '{{"use_brute_force":true}}'
    )
    ORDER BY distance ASC
    """
    rows = bq.query(sql, metro=config.METRO, q=intake_description, top_k=top_k)

    street = _street_key(block_or_street) if block_or_street else ""
    accepted, rejected = [], []
    for rank, row in enumerate(rows, start=1):
        row["semantic_rank"] = rank
        row["planted_teaching_decoy"] = _is_planted(row)
        reasons = _rejection_reasons(row)
        if reasons:
            row["rejection_reasons"] = reasons
            rejected.append(row)
            continue
        if street:
            row["same_street_as_tenant"] = street in (row.get("block_address") or "").lower()
        if census_tract_geoid:
            row["same_tract_as_tenant"] = row.get("census_tract_geoid") == census_tract_geoid
        accepted.append(row)

    # Same-street / same-tract evidence first, then semantic distance.
    accepted.sort(
        key=lambda r: (
            not r.get("same_street_as_tenant", False),
            not r.get("same_tract_as_tenant", False),
            r["cosine_distance"],
        )
    )
    if tool_context is not None and any(r.get("same_street_as_tenant") for r in accepted):
        tool_context.state["same_block_open_case"] = True

    # Near-misses that semantic search alone would have surfaced near the top.
    outranked = [f"{r['request_id']} (rank {r['semantic_rank']})" for r in rejected if r["semantic_rank"] <= 5]
    return {
        "metro": config.METRO,
        "query_used": intake_description,
        "candidates_scanned": len(rows),
        "open_case_scope_supported": (
            "same_building_or_block"
            if any(r.get("same_street_as_tenant") for r in accepted)
            else "none"
        ),
        "accepted_evidence": accepted[:10],
        "rejected_candidates": rejected,
        "summary": (
            f"{len(accepted)} open residential complaints accepted, {len(rejected)} near-misses "
            f"rejected by the post-filter. Rejected rows that raw vector search ranked in the "
            f"top 5: {outranked or 'none'}."
        ),
        "provenance_note": "311 rows are real public DBI records (100-block redacted) "
        "except rows marked planted_teaching_decoy, which are synthetic test cases.",
    }


def locate_block(block_or_street: str) -> dict[str, Any]:
    """Find which census tract(s) a street or 100-block falls in, using 311 block addresses.

    Args:
        block_or_street: Street name or 100-block, e.g. "Ellis St" or "400 block of Ellis".

    Returns:
        dict with matching tract GEOIDs (strings) and how many complaints are on that street.
    """
    key = _street_key(block_or_street)
    if not key:
        return {"error": "Could not find a street name in the input."}
    sql = f"""
    SELECT census_tract_geoid,
           ARRAY_AGG(DISTINCT block_address LIMIT 5) AS example_blocks,
           COUNT(*) AS complaints_total,
           COUNTIF(property_type = 'Residential' AND closed_date IS NULL) AS open_residential
    FROM {table('municipal_311_housing_complaints')}
    WHERE metro_area = @metro AND LOWER(block_address) LIKE @pat
    GROUP BY census_tract_geoid
    ORDER BY complaints_total DESC
    LIMIT 10
    """
    rows = bq.query(sql, metro=config.METRO, pat=f"%{key}%")
    return {"street_key": key, "tracts": rows, "found": bool(rows)}


def match_statutes(hazard_description: str, top_k: int = 3) -> dict[str, Any]:
    """Find the state/local housing statutes most relevant to a tenant's hazard and situation.

    Uses VECTOR_SEARCH over embedded statute text for this metro's state.

    Args:
        hazard_description: Hazard plus legal posture, e.g. "no heat, leaking
            electrical, 3-day pay-or-quit notice, nonpayment hearing Monday".
        top_k: How many statutes to return.

    Returns:
        dict with statutes ranked by semantic relevance, including code_citation and text.
    """
    sql = f"""
    SELECT base.statute_section_id, base.code_citation, base.ordinance_title,
           base.jurisdiction, base.raw_statute_text, base.data_provenance,
           ROUND(distance, 4) AS cosine_distance
    FROM VECTOR_SEARCH(
      (SELECT * FROM {table('statutes_embedded')} WHERE state_code = @state),
      'embedding',
      (SELECT {_embed_expr('@q')} AS query_vec),
      query_column_to_search => 'query_vec',
      top_k => @top_k,
      distance_type => 'COSINE',
      options => '{{"use_brute_force":true}}'
    )
    ORDER BY distance ASC
    """
    rows = bq.query(sql, state=config.STATE_CODE, q=hazard_description, top_k=int(top_k or 3))
    return {"statutes": rows}


_OPEN_CASE_SCOPES = ("own_unit", "same_building_or_block", "none")


def check_relief_eligibility(
    household_situation: str,
    open_case_scope: str,
    is_residential_tenant: bool = True,
    tool_context: Optional[ToolContext] = None,
) -> dict[str, Any]:
    """Rank this metro's emergency rental relief programs and apply their hard eligibility rules.

    Semantic fit comes from VECTOR_SEARCH over bulletin text. Hard rules come
    from the structured columns: requires_open_habitability_case and
    residential_tenants_only. A program that fails a hard rule is returned as
    ineligible with the reason, never silently dropped.

    Args:
        household_situation: e.g. "family of 3, lost shifts, $4,200 arrears,
            nonpayment hearing Monday, no heat".
        open_case_scope: How strong the open-habitability-case proof is:
            "own_unit" = tenant has their own open DBI case number;
            "same_building_or_block" = search_habitability_evidence accepted an open
            residential case on the tenant's street/block (same_street_as_tenant=True);
            "none" = no open residential case corroborated.
        is_residential_tenant: False for commercial tenants.

    Returns:
        dict with 'eligible_programs', 'conditionally_eligible_programs' and
        'ineligible_programs' (each with reasons / what would unlock them).
    """
    sql = f"""
    SELECT base.bulletin_id, base.program_name, base.administering_agency,
           base.funding_stream, base.requires_open_habitability_case,
           base.residential_tenants_only, base.raw_bulletin_text, base.intake_url,
           base.effective_date, ROUND(distance, 4) AS cosine_distance
    FROM VECTOR_SEARCH(
      (SELECT * FROM {table('bulletins_embedded')} WHERE metro_area = @metro),
      'embedding',
      (SELECT {_embed_expr('@q')} AS query_vec),
      query_column_to_search => 'query_vec',
      top_k => 10,
      distance_type => 'COSINE',
      options => '{{"use_brute_force":true}}'
    )
    ORDER BY distance ASC
    """
    scope = (open_case_scope or "none").strip().lower()
    if scope not in _OPEN_CASE_SCOPES:
        scope = "none"
    # Evidence found earlier in this session overrides a weaker scope from the model.
    if scope == "none" and tool_context is not None and tool_context.state.get("same_block_open_case"):
        scope = "same_building_or_block"
    rows = bq.query(sql, metro=config.METRO, q=household_situation)
    eligible, conditional, ineligible = [], [], []
    for r in rows:
        if r["residential_tenants_only"] and not is_residential_tenant:
            r["ineligible_because"] = ["residential tenants only"]
            ineligible.append(r)
        elif r["requires_open_habitability_case"] and scope == "none":
            r["ineligible_because"] = [
                "requires an open, un-abated residential habitability case; none is corroborated"
            ]
            r["unlock_by"] = "Tenant files a DBI complaint for their unit today and an inspector opens a case."
            ineligible.append(r)
        elif r["requires_open_habitability_case"] and scope == "same_building_or_block":
            r["conditional_on"] = (
                "Open DBI case exists on the tenant's building/block, but it is not confirmed to cover "
                "this tenant's unit. Confirm the unit is named in that case or file the tenant's own complaint."
            )
            conditional.append(r)
        else:
            r["note"] = "Passes the structured rules. Income/AMI limits in the bulletin text still need to be verified at intake."
            eligible.append(r)
    return {
        "open_case_scope_used": scope,
        "eligible_programs": eligible,
        "conditionally_eligible_programs": conditional,
        "ineligible_programs": ineligible,
    }


_TRACT_CTE = f"""
WITH filings AS (  -- pre-aggregate 4 quarters per tract BEFORE joining
  SELECT census_tract_geoid,
         SUM(nonpayment_filings_count) AS nonpayment_filings_4q,
         SUM(holdover_or_no_fault_filings_count) AS no_fault_filings_4q,
         SUM(default_judgments_count) AS default_judgments_4q,
         ROUND(AVG(median_claimed_arrears_usd)) AS avg_median_arrears_usd,
         ANY_VALUE(data_provenance) AS filings_provenance
  FROM {{filings}}
  WHERE metro_area = @metro
  GROUP BY census_tract_geoid
),
open311 AS (
  SELECT census_tract_geoid,
         COUNTIF(property_type = 'Residential' AND closed_date IS NULL) AS open_residential_311
  FROM {{complaints}}
  WHERE metro_area = @metro
  GROUP BY census_tract_geoid
),
tracts AS (
  SELECT a.census_tract_geoid, a.county_name, a.total_population, a.renter_occupied_units,
         a.median_household_income, a.median_gross_rent, a.poverty_rate, a.no_vehicle_rate,
         a.assistance_rate,
         SAFE_DIVIDE(a.renter_hh_rent_50_pct_plus_count, a.renter_occupied_units) AS severe_rent_burden_rate,
         a.audit_black_share, a.audit_hispanic_share, a.audit_asian_share,
         a.audit_indigenous_share, a.audit_white_share,
         f.nonpayment_filings_4q, f.no_fault_filings_4q, f.default_judgments_4q,
         f.avg_median_arrears_usd,
         SAFE_DIVIDE(f.nonpayment_filings_4q + f.no_fault_filings_4q, a.renter_occupied_units) * 100
           AS filings_per_100_renter_units,
         IFNULL(o.open_residential_311, 0) AS open_residential_311,
         a.data_provenance AS acs_provenance, f.filings_provenance
  FROM {{acs}} a
  LEFT JOIN filings f USING (census_tract_geoid)
  LEFT JOIN open311 o USING (census_tract_geoid)
  WHERE a.metro_area = @metro
),
ranked AS (
  SELECT *,
    ROUND(PERCENT_RANK() OVER (ORDER BY filings_per_100_renter_units), 2) AS filing_pressure_pctile,
    ROUND(PERCENT_RANK() OVER (ORDER BY severe_rent_burden_rate), 2) AS rent_burden_pctile,
    ROUND(PERCENT_RANK() OVER (ORDER BY open_residential_311), 2) AS open_311_pctile
  FROM tracts
)
"""


def _tract_cte() -> str:
    return _TRACT_CTE.format(
        filings=table("court_eviction_filings"),
        complaints=table("municipal_311_housing_complaints"),
        acs=table("acs_tract_housing_tenure"),
    )


def get_tract_context(census_tract_geoid: str) -> dict[str, Any]:
    """Neighbourhood context for one census tract compared with the rest of the metro.

    Describes the NEIGHBOURHOOD, not the individual household. Eviction filings
    are modeled (not real court records); ACS figures are real Census estimates.

    Args:
        census_tract_geoid: 11-digit tract GEOID as a string (keep the leading zero, e.g. "06075012400").

    Returns:
        dict with tract stats, metro percentiles, and metro medians.
    """
    geoid = str(census_tract_geoid).strip().zfill(11)
    sql = _tract_cte() + """
    SELECT * FROM ranked WHERE census_tract_geoid = @geoid
    """
    rows = bq.query(sql, metro=config.METRO, geoid=geoid)
    medians = bq.query(_tract_cte() + """
    SELECT
      APPROX_QUANTILES(filings_per_100_renter_units, 2)[OFFSET(1)] AS metro_median_filings_per_100,
      APPROX_QUANTILES(severe_rent_burden_rate, 2)[OFFSET(1)] AS metro_median_severe_burden,
      APPROX_QUANTILES(open_residential_311, 2)[OFFSET(1)] AS metro_median_open_311
    FROM ranked
    """, metro=config.METRO)
    if not rows:
        return {"error": f"Tract {geoid} not found in {config.METRO}."}
    return {
        "tract": rows[0],
        "metro_medians": medians[0] if medians else {},
        "caveat": "Filings are MODELED from county court baselines (Eviction Lab has no California "
        "coverage). ACS rent burden is real. These describe the neighbourhood, not this household.",
    }


def find_silent_distress_tracts(limit: int = 8) -> dict[str, Any]:
    """Equity audit: tracts with high eviction pressure and rent burden but few open 311 complaints.

    These are places where requiring an open 311/DBI case to unlock relief may
    under-serve tenants who fear retaliation or don't call inspectors. The
    audit_* demographic shares are reported for auditing only and are never
    used as a scoring input.

    Args:
        limit: Number of tracts to return.

    Returns:
        dict with 'silent_distress_tracts', the metro baseline, and the audit comparison.
    """
    sql = _tract_cte() + """
    , scored AS (
      SELECT *, ROUND((filing_pressure_pctile + rent_burden_pctile) / 2 - open_311_pctile, 3)
                AS silent_distress_score
      FROM ranked
    )
    SELECT census_tract_geoid, renter_occupied_units, severe_rent_burden_rate,
           filings_per_100_renter_units, open_residential_311, no_vehicle_rate,
           poverty_rate, filing_pressure_pctile, rent_burden_pctile, open_311_pctile,
           silent_distress_score, audit_black_share, audit_hispanic_share,
           audit_asian_share, audit_white_share
    FROM scored
    ORDER BY silent_distress_score DESC
    LIMIT @lim
    """
    rows = bq.query(sql, metro=config.METRO, lim=int(limit or 8))
    baseline = bq.query(_tract_cte() + """
    SELECT
      SUM(renter_occupied_units) AS renter_units,
      SAFE_DIVIDE(SUM(severe_rent_burden_rate * renter_occupied_units), SUM(renter_occupied_units)) AS severe_burden,
      SAFE_DIVIDE(SUM(no_vehicle_rate * total_population), SUM(total_population)) AS no_vehicle_rate,
      SAFE_DIVIDE(SUM(audit_black_share * total_population), SUM(total_population)) AS audit_black_share,
      SAFE_DIVIDE(SUM(audit_hispanic_share * total_population), SUM(total_population)) AS audit_hispanic_share,
      SAFE_DIVIDE(SUM(audit_asian_share * total_population), SUM(total_population)) AS audit_asian_share,
      SAFE_DIVIDE(SUM(audit_white_share * total_population), SUM(total_population)) AS audit_white_share,
      SUM(open_residential_311) AS open_residential_311
    FROM ranked
    """, metro=config.METRO)
    return {
        "silent_distress_tracts": rows,
        "metro_baseline": baseline[0] if baseline else {},
        "method": "score = mean(filing pressure pctile, severe rent burden pctile) - open 311 pctile. "
        "Demographic audit_* shares are NOT inputs; they are shown only to audit who the rule affects.",
        "caveat": "Filings are modeled; 311 volume reflects reporting behaviour, not true hazard prevalence.",
    }
