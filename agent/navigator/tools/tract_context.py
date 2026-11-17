"""Neighborhood context tool. Demographic audit fields stay separate."""

import re
from google.cloud import bigquery
from .. import config


def tract_context(census_tract_geoid: str) -> dict:
    """Get SF rent burden and four-quarter modeled eviction context.

    Args:
        census_tract_geoid: An 11-digit census tract ID, kept as a string.
    """
    if not isinstance(census_tract_geoid, str) or not re.fullmatch(
        r"\d{11}", census_tract_geoid
    ):
        return {"error": "Provide an 11-digit census tract ID as text."}

    dataset = f"{config.PROJECT}.{config.DATASET}"
    sql = f"""
    WITH acs AS (
      SELECT
        census_tract_geoid,
        renter_occupied_units,
        renter_hh_rent_50_pct_plus_count AS severe_households
      FROM `{dataset}.acs_tract_housing_tenure`
      WHERE metro_area = 'San Francisco'
    ),
    baseline AS (
      SELECT
        100.0 * SAFE_DIVIDE(
          SUM(severe_households), SUM(renter_occupied_units)
        ) AS metro_pct
      FROM acs
    ),
    filings AS (
      SELECT
        census_tract_geoid,
        COUNT(DISTINCT reporting_quarter) AS quarters_present,
        MIN(reporting_quarter) AS first_quarter,
        MAX(reporting_quarter) AS last_quarter,
        SUM(nonpayment_filings_count) AS nonpayment,
        SUM(holdover_or_no_fault_filings_count) AS other_filings
      FROM `{dataset}.court_eviction_filings`
      WHERE metro_area = 'San Francisco'
      GROUP BY census_tract_geoid
    )
    SELECT
      a.census_tract_geoid,
      a.renter_occupied_units,
      a.severe_households AS severely_burdened_households,
      ROUND(
        100.0 * SAFE_DIVIDE(
          a.severe_households, a.renter_occupied_units
        ), 1
      ) AS severe_rent_burden_pct,
      ROUND(b.metro_pct, 1) AS metro_severe_rent_burden_pct,
      f.quarters_present,
      f.first_quarter,
      f.last_quarter,
      f.nonpayment AS modeled_nonpayment_filings,
      f.other_filings AS modeled_other_filings,
      f.nonpayment + f.other_filings AS annual_filings_modeled
    FROM acs a
    CROSS JOIN baseline b
    LEFT JOIN filings f USING (census_tract_geoid)
    WHERE a.census_tract_geoid = @tract
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "tract", "STRING", census_tract_geoid
            )
        ]
    )
    client = bigquery.Client(project=config.PROJECT)
    try:
        rows = list(client.query(sql, job_config=job_config).result())
    finally:
        client.close()

    if not rows:
        return {"error": "Tract not found in the supplied SF dataset."}

    result = dict(rows[0])
    result["filings_provenance"] = "modeled"
    result["metro_baseline_method"] = "Weighted by renter households"
    result["note"] = (
        "Neighborhood context, not the tenant's court record. "
        "Filings cover the first_quarter through last_quarter shown. "
        "Check quarters_present before describing them as annual."
    )
    result["sources"] = [
        f"{dataset}.acs_tract_housing_tenure",
        f"{dataset}.court_eviction_filings",
    ]
    return result
