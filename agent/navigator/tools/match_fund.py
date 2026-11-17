"""Screen supplied SF programs. Results require intake verification."""

import math
from google.cloud import bigquery
from .. import config


def match_fund(
    income_pct_ami: float,
    household_size: int,
    has_open_habitability_case: bool,
    is_residential: bool = True,
    has_medical_leave_or_wage_loss: bool = None,
    has_qualifying_unit_dbi_notice: bool = None,
    has_unlawful_detainer_case: bool = None,
) -> dict:
    """Screen the household against the supplied SF program bulletins.

    Never infer a tenant's own DBI case from a block-level complaint.
    Conditional means additional facts are required, not confirmed eligibility.

    Args:
        income_pct_ami: Income percent of AMI adjusted for household size.
        household_size: Number of household members.
        has_open_habitability_case: Tenant has an active open DBI case.
        is_residential: Whether this is a residential tenancy.
        has_medical_leave_or_wage_loss: Confirmed hardship, or omit if unknown.
        has_qualifying_unit_dbi_notice: Tenant's unit has an open unabated
            DBI notice for no heat, raw sewage, or toxic mold, or omit if unknown.
        has_unlawful_detainer_case: Tenant faces unlawful detainer proceedings,
            or omit if unknown.
    """
    if (
        not isinstance(household_size, int)
        or isinstance(household_size, bool)
        or household_size < 1
    ):
        return {"error": "Household size must be a positive integer."}
    if (
        not isinstance(income_pct_ami, (int, float))
        or isinstance(income_pct_ami, bool)
        or not math.isfinite(income_pct_ami)
        or income_pct_ami < 0
    ):
        return {"error": "Provide a valid nonnegative income percent of AMI."}

    dataset = f"{config.PROJECT}.{config.DATASET}"
    client = None
    try:
        client = bigquery.Client(project=config.PROJECT)
        rows = list(client.query(f"""
            SELECT bulletin_id, program_name, administering_agency,
                   requires_open_habitability_case, residential_tenants_only,
                   raw_bulletin_text, intake_url
            FROM `{dataset}.rental_relief_program_bulletins`
            WHERE metro_area = 'San Francisco'
            ORDER BY bulletin_id
        """, timeout=60).result(timeout=60))
    except Exception as exc:
        return {"error": f"Fund query failed: {exc}"}
    finally:
        if client is not None:
            client.close()

    funds = []
    for row in rows:
        r = dict(row)
        bulletin = r["bulletin_id"]
        text = r["raw_bulletin_text"] or ""
        failed, missing = [], []

        if r["residential_tenants_only"] and not is_residential:
            failed.append("Requires a residential tenancy.")
        if r["requires_open_habitability_case"] and not has_open_habitability_case:
            failed.append("Requires the tenant's own active open DBI case.")

        if bulletin in ("BUL-CA-01", "BUL-CA-03"):
            cap = 80 if bulletin == "BUL-CA-01" else 60
            if f"{cap}%" not in text:
                missing.append("Bulletin changed: verify its income cap.")
            elif income_pct_ami > cap:
                failed.append(f"Income {income_pct_ami}% AMI exceeds {cap}% cap.")

        extra_rule = {
            "BUL-CA-03": (
                has_medical_leave_or_wage_loss,
                "Medical leave or wage loss",
            ),
            "BUL-CA-04": (
                has_qualifying_unit_dbi_notice,
                "Open unabated unit DBI notice for no heat, sewage, or toxic mold",
            ),
            "BUL-CA-02": (
                has_unlawful_detainer_case,
                "Unlawful detainer proceeding",
            ),
        }.get(bulletin)

        if extra_rule:
            value, description = extra_rule
            if value is None:
                missing.append(description)
            elif value is False:
                failed.append(f"Requirement not met: {description}.")

        if bulletin not in {"BUL-CA-01", "BUL-CA-02", "BUL-CA-03", "BUL-CA-04"}:
            missing.append("Program rules require review.")

        fit = "not_eligible" if failed else "conditional" if missing else "likely"
        funds.append({
            **r,
            "eligible": fit == "likely",
            "fit": fit,
            "why": " ".join(failed) if failed else (
                "Confirm: " + "; ".join(missing)
                if missing else "Meets the supplied bulletin screening criteria."
            ),
            "missing_inputs": missing,
        })

    return {
        "funds": funds,
        "note": (
            "Screening against supplied summarized bulletins, not an approval "
            "or confirmation of current funding availability. Conditional "
            "results have eligible=False until required facts are confirmed."
        ),
        "sources": [f"{dataset}.rental_relief_program_bulletins"],
    }
