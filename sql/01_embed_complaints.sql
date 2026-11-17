-- Builds a4i_housing.complaints_embedded: every column of municipal_311_housing_complaints plus a plain ARRAY<FLOAT64> embedding.
-- Model: gemini-embedding-2 (3072 dims) via the us.a4i-vertex CLOUD_RESOURCE connection.
-- Must match agent/navigator/config.py (EMBED_ENDPOINT, EMBED_CONNECTION).
-- Run: bq query --use_legacy_sql=false --location=US < sql/01_embed_complaints.sql
CREATE OR REPLACE TABLE a4i_housing.complaints_embedded AS
SELECT * EXCEPT (embedded), embedded.result AS embedding
FROM (
  SELECT *, AI.EMBED(complaint_narrative, connection_id => 'us.a4i-vertex',
                     endpoint => 'gemini-embedding-2') AS embedded
  FROM a4i_housing.municipal_311_housing_complaints
)
WHERE embedded.status = '';  -- drop rows where embedding failed
