-- Builds a4i_housing.bulletins_embedded: every column of rental_relief_program_bulletins plus a plain ARRAY<FLOAT64> embedding.
-- Model: gemini-embedding-2 (3072 dims) via the us.a4i-vertex CLOUD_RESOURCE connection.
-- Must match agent/navigator/config.py (EMBED_ENDPOINT, EMBED_CONNECTION).
-- Run: bq query --use_legacy_sql=false --location=US < sql/03_embed_bulletins.sql
CREATE OR REPLACE TABLE a4i_housing.bulletins_embedded AS
SELECT * EXCEPT (embedded), embedded.result AS embedding
FROM (
  SELECT *, AI.EMBED(CONCAT(program_name, '. ', raw_bulletin_text), connection_id => 'us.a4i-vertex',
                     endpoint => 'gemini-embedding-2') AS embedded
  FROM a4i_housing.rental_relief_program_bulletins
)
WHERE embedded.status = '';  -- drop rows where embedding failed
