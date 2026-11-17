"""TEMPORARY stand-ins for Prachi's tools so the agent runs end to end today.

Owner: Karthik. Delete each stub once Prachi's real file lands in tools/:
match_fund.py, tract_context.py, equity_audit.py. tools/__init__.py picks the real one
automatically when it exists. Every stub result carries "stub": true so it can't be demoed
by accident.
"""

_SF_FUNDS = [
    # (program, agency, AMI cap %, needs open habitability case, intake_url)
    ("San Francisco Emergency Rental Assistance Program (SF ERAP)",
     "San Francisco Mayor's Office of Housing and Community Development", 80, False, "https://sf.gov/renthelp"),
    ("RadCo / Mission Economic Development Family Stabilization Grant",
     "MEDA San Francisco", 60, False, "https://medasf.org"),
    ("Code Enforcement Relocation & Mold Remediation Bridge",
     "SF Department of Building Inspection Tenant Relocation Fund", None, True, "https://sf.gov/dbi"),
    ("Proposition F Tenant Right to Counsel & Habitability Defense",
     "Eviction Defense Collaborative", None, True, "https://evictiondefense.org"),
]


def match_fund(
    income_pct_ami: float,
    household_size: int,
    has_open_habitability_case: bool,
    is_residential: bool = True,
) -> dict:
    """Check the tenant against each San Francisco emergency fund's eligibility rules.

    Args:
        income_pct_ami: Household income as a percent of Area Median Income, e.g. 45.
        household_size: Number of people in the household.
        has_open_habitability_case: True if there is an open, un-abated DBI habitability case.
        is_residential: True for a residential tenancy.
    """
    funds = []
    for name, agency, cap, needs_case, url in _SF_FUNDS:
        why = []
        ok = is_residential
        if not is_residential:
            why.append("residential tenants only")
        if cap is not None:
            ok = ok and income_pct_ami <= cap
            why.append(f"{income_pct_ami:g}% AMI {'≤' if income_pct_ami <= cap else '>'} {cap}% cap")
        if needs_case:
            ok = ok and has_open_habitability_case
            why.append("open habitability case " + ("present" if has_open_habitability_case else "required, none found"))
        funds.append({
            "program_name": name, "administering_agency": agency, "eligible": ok,
            "why": "; ".join(why), "requires_open_habitability_case": needs_case, "intake_url": url,
        })
    return {"stub": True, "funds": funds}


def tract_context(census_tract_geoid: str) -> dict:
    """Neighborhood context for a census tract: rent burden and modeled eviction filings.

    Args:
        census_tract_geoid: 11-character tract GEOID as a string, e.g. "06075012400".
    """
    return {
        "stub": True,
        "census_tract_geoid": census_tract_geoid,
        "severe_rent_burden_pct": None,
        "metro_severe_rent_burden_pct": 17.5,
        "annual_filings_modeled": None,
        "note": "Stub: Prachi's tract_context is not merged yet.",
    }


def equity_audit(census_tract_geoids: list[str]) -> dict:
    """Post-output equity audit for the tracts in a finished brief. Never used for ranking.

    Args:
        census_tract_geoids: Tract GEOIDs (strings) that appear in the brief.
    """
    return {
        "stub": True,
        "census_tract_geoids": census_tract_geoids,
        "note": "Stub: Prachi's equity_audit is not merged yet.",
    }

