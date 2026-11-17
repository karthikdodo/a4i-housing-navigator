"""Post-output equity audit. Never use for ranking."""

import re
from google.cloud import bigquery
from .. import config


def equity_audit(census_tract_geoids: list[str]) -> dict:
    """Compare completed brief tracts with the SF demographic baseline.

    Call only after submitting the brief. Never use for ranking.

    Args:
        census_tract_geoids: List of 11-digit tract IDs in the finished brief.
    """
    if not census_tract_geoids or any(
        not isinstance(g, str) or not re.fullmatch(r"\d{11}", g)
        for g in census_tract_geoids
    ):
        return {"error": "Provide a nonempty list of 11-digit tract strings."}

    geoids = sorted(set(census_tract_geoids))
    fields = [
        "audit_black_share",
        "audit_hispanic_share",
        "audit_asian_share",
        "audit_indigenous_share",
        "audit_white_share",
    ]
    dataset = f"{config.PROJECT}.{config.DATASET}"
    sql = f"""
    SELECT census_tract_geoid, {", ".join(fields)}
    FROM `{dataset}.acs_tract_housing_tenure`
    WHERE metro_area = 'San Francisco'
    """
    client = None
    try:
        client = bigquery.Client(project=config.PROJECT)
        rows = [
            dict(row)
            for row in client.query(sql, timeout=60).result(timeout=60)
        ]
    except Exception as exc:
        return {"error": f"Equity audit query failed: {exc}"}
    finally:
        if client is not None:
            client.close()

    selected = [r for r in rows if r["census_tract_geoid"] in geoids]
    missing = sorted(
        set(geoids) - {r["census_tract_geoid"] for r in selected}
    )
    if missing:
        return {"error": "Tracts not found in SF.", "missing": missing}

    def average(records, field):
        values = [
            float(r[field]) for r in records if r[field] is not None
        ]
        return sum(values) / len(values) if values else None

    comparisons = []
    for field in fields:
        local = average(selected, field)
        metro = average(rows, field)
        comparisons.append({
            "metric": field,
            "selected_tracts_pct": (
                round(100 * local, 1) if local is not None else None
            ),
            "metro_pct": (
                round(100 * metro, 1) if metro is not None else None
            ),
            "difference_percentage_points": (
                round(100 * (local - metro), 1)
                if local is not None and metro is not None else None
            ),
        })

    return {
        "census_tract_geoids": geoids,
        "selected_tract_count": len(selected),
        "metro_tract_count": len(rows),
        "comparisons": comparisons,
        "baseline_method": "Unweighted average across supplied SF tracts",
        "audit_only": True,
        "used_in_ranking": False,
        "note": "Neighborhood demographics, not tenant demographics.",
        "sources": [f"{dataset}.acs_tract_housing_tenure"],
    }
