-- One-time setup: materialize embeddings for the searchable corpora.
-- Uses text-embedding-005 with the caller's credentials (no CLOUD_RESOURCE connection),
-- matching the team's existing a4i_housing.complaint_embeddings table.
-- Run with:
--   bq query --project_id=<PROJECT> --use_legacy_sql=false --location=US < agent/setup_embeddings.sql
--
-- 311 complaints are already embedded in a4i_housing.complaint_embeddings:
--   CREATE OR REPLACE TABLE a4i_housing.complaint_embeddings AS
--   SELECT *, AI.EMBED(complaint_narrative, endpoint => 'text-embedding-005').result AS embedding
--   FROM a4i_housing.municipal_311_housing_complaints;

CREATE OR REPLACE TABLE a4i_housing.statutes_embedded AS
SELECT
  statute_section_id, state_code, metro_area, jurisdiction, code_citation,
  ordinance_title, raw_statute_text, data_provenance,
  embedded.result AS embedding
FROM (
  SELECT *,
    AI.EMBED(CONCAT(ordinance_title, '. ', raw_statute_text),
             endpoint => 'text-embedding-005') AS embedded
  FROM a4i_housing.municipal_housing_ordinance_statutes
)
WHERE embedded.status = '';

CREATE OR REPLACE TABLE a4i_housing.bulletins_embedded AS
SELECT
  bulletin_id, state_code, metro_area, service_region, program_name, administering_agency,
  funding_stream, requires_open_habitability_case, residential_tenants_only,
  raw_bulletin_text, intake_url, effective_date, data_provenance,
  embedded.result AS embedding
FROM (
  SELECT *,
    AI.EMBED(CONCAT(program_name, '. ', raw_bulletin_text),
             endpoint => 'text-embedding-005') AS embedded
  FROM a4i_housing.rental_relief_program_bulletins
)
WHERE embedded.status = '';

SELECT 'complaints' AS t, COUNT(*) AS n FROM a4i_housing.complaint_embeddings
UNION ALL SELECT 'statutes', COUNT(*) FROM a4i_housing.statutes_embedded
UNION ALL SELECT 'bulletins', COUNT(*) FROM a4i_housing.bulletins_embedded;
