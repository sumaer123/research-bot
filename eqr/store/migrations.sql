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
-- Wave 3 / Layer 1: decision engine columns (verdict lives in ratings.rating, DCI in ratings.confidence)
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS rule_id VARCHAR;
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS profile VARCHAR;
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS mos_base DOUBLE;
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS fv_base DOUBLE;
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS fv_bull DOUBLE;
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS fv_bear DOUBLE;
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS dci_band VARCHAR;
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS valuation_json VARCHAR;
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS decision_json VARCHAR;
ALTER TABLE ratings ADD COLUMN IF NOT EXISTS price DOUBLE;
ALTER TABLE rating_ledger ADD COLUMN IF NOT EXISTS mos_at_publish DOUBLE;
ALTER TABLE rating_ledger ADD COLUMN IF NOT EXISTS dci_at_publish DOUBLE;
ALTER TABLE rating_ledger ADD COLUMN IF NOT EXISTS verdict_prev VARCHAR;
