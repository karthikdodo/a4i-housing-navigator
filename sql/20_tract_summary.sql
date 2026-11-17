-- SF tract context. Aggregate four quarters before joining.
-- Eviction figures are modeled, not actual court records.
WITH evictions AS (
  SELECT
    census_tract_geoid,
    COUNT(DISTINCT reporting_quarter) AS quarters_present,
    MIN(reporting_quarter) AS first_quarter,
    MAX(reporting_quarter) AS last_quarter,
    SUM(nonpayment_filings_count) AS modeled_nonpayment_filings,
    SUM(holdover_or_no_fault_filings_count) AS modeled_other_filings
  FROM
    `qwiklabs-gcp-04-3b4b41069fc3.a4i_housing.court_eviction_filings`
  WHERE metro_area = 'San Francisco'
  GROUP BY census_tract_geoid
)
SELECT
  a.census_tract_geoid,
  ROUND(
    100.0 * SAFE_DIVIDE(
      a.renter_hh_rent_50_pct_plus_count,
      a.renter_occupied_units
    ), 1
  ) AS severe_rent_burden_pct,
  e.quarters_present,
  e.first_quarter,
  e.last_quarter,
  e.modeled_nonpayment_filings,
  e.modeled_other_filings
FROM
  `qwiklabs-gcp-04-3b4b41069fc3.a4i_housing.acs_tract_housing_tenure` a
LEFT JOIN evictions e USING (census_tract_geoid)
WHERE a.metro_area = 'San Francisco'
ORDER BY severe_rent_burden_pct DESC;
