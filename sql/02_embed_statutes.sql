-- Builds a4i_housing.statutes_embedded: every column of municipal_housing_ordinance_statutes plus a plain ARRAY<FLOAT64> embedding.
-- Model: gemini-embedding-2 (3072 dims) via the us.a4i-vertex CLOUD_RESOURCE connection.
-- Must match agent/navigator/config.py (EMBED_ENDPOINT, EMBED_CONNECTION).
-- Run: bq query --use_legacy_sql=false --location=US < sql/02_embed_statutes.sql
CREATE OR REPLACE TABLE a4i_housing.statutes_embedded AS
SELECT * EXCEPT (embedded), embedded.result AS embedding
FROM (
  SELECT *, AI.EMBED(CONCAT(ordinance_title, '. ', raw_statute_text), connection_id => 'us.a4i-vertex',
                     endpoint => 'gemini-embedding-2') AS embedded
  FROM a4i_housing.municipal_housing_ordinance_statutes
)
WHERE embedded.status = '';  -- drop rows where embedding failed
