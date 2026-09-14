ALTER TABLE results_calendar ADD COLUMN IF NOT EXISTS xbrl_url VARCHAR;
ALTER TABLE results_calendar ADD COLUMN IF NOT EXISTS seq_id VARCHAR;
ALTER TABLE results_calendar ADD COLUMN IF NOT EXISTS type_sub VARCHAR;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS extract_status VARCHAR;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS schema_version INTEGER;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS engine_rating VARCHAR;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS llm_view VARCHAR;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS run_id VARCHAR;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS status VARCHAR;
ALTER TABLE dossiers ADD COLUMN IF NOT EXISTS errors_json VARCHAR;
-- Latest STORED dossier per (symbol, as_of); rejected/superseded runs stay in the base table.
CREATE VIEW IF NOT EXISTS dossiers_current AS
  SELECT * FROM dossiers WHERE status = 'STORED'
  QUALIFY row_number() OVER (PARTITION BY symbol, as_of ORDER BY created_at DESC) = 1;
