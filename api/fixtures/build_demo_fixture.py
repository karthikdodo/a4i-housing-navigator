"""Build the demo-mode replay fixture from the organizer data in data/*.parquet.

Demo mode (A4I_AGENT_MODE=mock) replays one scripted intake so the UI can be built and
demoed without GCP credentials. Every record, statute, fund and tract figure here is copied
from the challenge dataset. Only the similarity scores are fixed replay values (live mode
gets real ones from BigQuery VECTOR_SEARCH).

Run from the repo root (needs pandas + pyarrow):
    python api/fixtures/build_demo_fixture.py
"""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = Path(__file__).with_name("demo_int_1142.json")

METRO = "San Francisco"
TENANT_TRACT = "06075033204"

# Replay similarity scores (cosine, 1 - distance). Live mode computes these.
MATCHES = {"SF-202665044": 0.86, "SF-202665131": 0.81, "SF-202665071": 0.64}
ON_BLOCK = {"SF-202665044"}
EXCLUDED = {"DECOY-SANF-05": 0.89, "DECOY-SANF-02": 0.84, "DECOY-SANF-01": 0.78, "DECOY-SANF-07": 0.71}
STATUTE_SIM = {"STAT-CA-01": 0.83, "STAT-CA-03": 0.74, "STAT-CA-02": 0.69}


def exclusion_reason(row) -> str:
    # Same rule order as agent/navigator/tools/semantic_search.py
    if row["property_type"] != "Residential":
        return "Commercial property"
    if row["inspection_status"] == "Closed - No Violation":
        return "Inspector found no violation"
    return f"Case closed ({row['inspection_status']}, {row['closed_date']})"


def main() -> None:
    c = pd.read_parquet(DATA / "municipal_311_housing_complaints.parquet")
    c = c[c.metro_area == METRO].set_index("request_id")

    matches = []
    for rid, sim in MATCHES.items():
        r = c.loc[rid]
        matches.append({
            "request_id": rid,
            "block_address": r.block_address,
            "census_tract_geoid": str(r.census_tract_geoid),
            "property_type": r.property_type,
            "raw_complaint_type": r.raw_complaint_type,
            "inspection_status": r.inspection_status,
            "created_date": str(r.created_date),
            "closed_date": None,
            "narrative": r.complaint_narrative[:600],
            "data_provenance": r.data_provenance,
            "latitude": round(float(r.latitude), 6),
            "longitude": round(float(r.longitude), 6),
            "similarity": sim,
            "on_tenant_block": rid in ON_BLOCK,
            "planted_decoy": False,
        })
    excluded = []
    for rid, sim in EXCLUDED.items():
        r = c.loc[rid]
        excluded.append({
            "request_id": rid,
            "reason": exclusion_reason({**r.to_dict(), "closed_date": r.closed_date}),
            "similarity": sim,
            "block_address": r.block_address,
            "raw_complaint_type": r.raw_complaint_type,
            "inspection_status": r.inspection_status,
            "property_type": r.property_type,
            "closed_date": None if pd.isna(r.closed_date) else str(r.closed_date),
            "narrative": r.complaint_narrative[:300],
            "planted_decoy": True,
        })

    s = pd.read_parquet(DATA / "municipal_housing_ordinance_statutes.parquet").set_index("statute_section_id")
    statutes = [{
        "statute_section_id": sid,
        "jurisdiction": s.loc[sid].jurisdiction,
        "code_citation": s.loc[sid].code_citation,
        "ordinance_title": s.loc[sid].ordinance_title,
        "text": s.loc[sid].raw_statute_text,
        "data_provenance": s.loc[sid].data_provenance,
        "similarity": sim,
    } for sid, sim in STATUTE_SIM.items()]

    b = pd.read_parquet(DATA / "rental_relief_program_bulletins.parquet")
    b = b[b.metro_area == METRO]
    bulletins = {r.bulletin_id: r for r in b.itertuples()}

    # match_fund in the shape docs/AGENT_REQUIREMENTS.md asks for (fit + missing_inputs).
    # Household income is unknown in this intake, so the AMI-capped funds need income.
    fund_rows = [
        ("BUL-CA-02", "likely", False, "Residential; open DBI habitability case on her block (SF-202665044). Confirm a unit-level DBI complaint.", ["unit_dbi_complaint"]),
        ("BUL-CA-01", "needs_info", False, "No open case required. Eligible if household is at or below 80% AMI (priority at or below 30%).", ["income_pct_ami"]),
        ("BUL-CA-04", "conditional", False, "Requires an open, un-abated DBI notice on her unit. The block record is not her unit: file a 311/DBI complaint today.", ["unit_dbi_complaint"]),
        ("BUL-CA-03", "needs_info", False, "At or below 60% AMI and acute medical leave or wage loss. Neither is known yet.", ["income_pct_ami", "wage_loss_or_medical_leave"]),
    ]
    funds = []
    for bid, fit, eligible, why, missing in fund_rows:
        r = bulletins[bid]
        funds.append({
            "bulletin_id": bid,
            "program_name": r.program_name,
            "administering_agency": r.administering_agency,
            "eligible": eligible,
            "fit": fit,
            "why": why,
            "missing_inputs": missing,
            "requires_open_habitability_case": bool(r.requires_open_habitability_case),
            "residential_tenants_only": bool(r.residential_tenants_only),
            "intake_url": r.intake_url,
            "bulletin_text": r.raw_bulletin_text,
        })

    a = pd.read_parquet(DATA / "acs_tract_housing_tenure.parquet")
    a = a[a.metro_area == METRO].copy()
    a["severe"] = a.renter_hh_rent_50_pct_plus_count / a.renter_occupied_units
    t = a[a.census_tract_geoid == TENANT_TRACT].iloc[0]
    f = pd.read_parquet(DATA / "court_eviction_filings.parquet")
    f = f[f.metro_area == METRO]
    per_tract = f.groupby("census_tract_geoid").agg(  # 4 quarters per tract: sum BEFORE joining
        filings=("nonpayment_filings_count", "sum"))
    tract_filings = int(per_tract.loc[TENANT_TRACT].filings)
    latest = f[f.census_tract_geoid == TENANT_TRACT].sort_values("reporting_quarter").iloc[-1]
    tract_context = {
        "census_tract_geoid": TENANT_TRACT,
        "severe_rent_burden_pct": round(float(t.severe) * 100, 1),
        "metro_severe_rent_burden_pct": round(
            float(a.renter_hh_rent_50_pct_plus_count.sum() / a.renter_occupied_units.sum()) * 100, 1),
        "annual_filings_modeled": tract_filings,
        "annual_filings_percentile": round(float((per_tract.filings < tract_filings).mean()) * 100),
        "median_claimed_arrears_usd": round(float(latest.median_claimed_arrears_usd)),
        "arrears_quarter": latest.reporting_quarter,
        "poverty_rate_pct": round(float(t.poverty_rate) * 100, 1),
        "metro_poverty_rate_pct": round(float(a.poverty_rate.mean()) * 100, 1),
    }

    shares = ["audit_hispanic_share", "audit_black_share", "audit_asian_share", "audit_white_share"]
    equity_audit = {
        "census_tract_geoids": [TENANT_TRACT],
        "used_in_ranking": False,
        "rows": [{
            "group": k.removeprefix("audit_").removesuffix("_share").title(),
            "tract_pct": round(float(t[k]) * 100, 1),
            "metro_pct": round(float(a[k].mean()) * 100, 1),
        } for k in shares],
        "baseline": "Unweighted mean across San Francisco tracts",
    }

    fixture = {
        "case_id": "INT-1142",
        "tool_results": {
            "complaints": {"backend": "replay", "corpus": "complaints", "matches": matches, "excluded": excluded,
                           "on_block_match_count": len(ON_BLOCK)},
            "statutes": {"backend": "replay", "corpus": "statutes", "matches": statutes},
            "match_fund": {"funds": funds},
            "tract_context": tract_context,
            "equity_audit": equity_audit,
        },
    }
    OUT.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
