-- eqr curated schema. Every table is idempotent (CREATE IF NOT EXISTS).
-- PIT law: as_of = the date a fact describes; visible_from = first date a strategy may use it.

CREATE TABLE IF NOT EXISTS instruments (
  symbol VARCHAR PRIMARY KEY, name VARCHAR, series VARCHAR, isin VARCHAR,
  listing_date DATE, face_value DOUBLE, paid_up_value DOUBLE, market_lot INTEGER,
  industry VARCHAR, sector VARCHAR, industry_source VARCHAR, as_of DATE);

CREATE TABLE IF NOT EXISTS prices_daily (
  trade_date DATE, symbol VARCHAR, series VARCHAR, isin VARCHAR, prev_close DOUBLE, open DOUBLE,
  high DOUBLE, low DOUBLE, close DOUBLE, last DOUBLE, vwap DOUBLE, volume BIGINT,
  turnover_inr DOUBLE, trades BIGINT, deliv_qty BIGINT, deliv_pct DOUBLE, source VARCHAR,
  PRIMARY KEY (trade_date, symbol, series));

CREATE TABLE IF NOT EXISTS trading_days (
  trade_date DATE PRIMARY KEY, n_rows INTEGER, source VARCHAR, loaded_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS adj_factors (
  symbol VARCHAR, ex_date DATE, factor DOUBLE, prev_close_reported DOUBLE,
  prior_close DOUBLE, kind VARCHAR, PRIMARY KEY (symbol, ex_date));

CREATE TABLE IF NOT EXISTS index_daily (
  trade_date DATE, index_name VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  points_change DOUBLE, pct_change DOUBLE, volume DOUBLE, turnover_cr DOUBLE,
  pe DOUBLE, pb DOUBLE, div_yield DOUBLE, PRIMARY KEY (trade_date, index_name));

CREATE TABLE IF NOT EXISTS corporate_actions (
  symbol VARCHAR, ex_date DATE, subject VARCHAR, record_date DATE, face_value DOUBLE,
  series VARCHAR, fetched_at TIMESTAMP, PRIMARY KEY (symbol, ex_date, subject));

CREATE TABLE IF NOT EXISTS statements (
  symbol VARCHAR, basis VARCHAR, stmt VARCHAR, period_end DATE, line_item VARCHAR,
  value DOUBLE, fetched_at TIMESTAMP, visible_from DATE,
  PRIMARY KEY (symbol, basis, stmt, period_end, line_item));

CREATE TABLE IF NOT EXISTS statement_revisions (
  symbol VARCHAR, basis VARCHAR, stmt VARCHAR, period_end DATE, line_item VARCHAR,
  value DOUBLE, fetched_at TIMESTAMP,
  PRIMARY KEY (symbol, basis, stmt, period_end, line_item, fetched_at));

CREATE TABLE IF NOT EXISTS shareholding (
  symbol VARCHAR, period_end DATE, holder VARCHAR, pct DOUBLE, fetched_at TIMESTAMP,
  visible_from DATE, PRIMARY KEY (symbol, period_end, holder));

CREATE TABLE IF NOT EXISTS results_calendar (
  symbol VARCHAR, period_end DATE, consolidated VARCHAR, filing_dt TIMESTAMP,
  audited VARCHAR, period VARCHAR, source VARCHAR,
  PRIMARY KEY (symbol, period_end, consolidated));

CREATE TABLE IF NOT EXISTS surveillance (
  as_of DATE, symbol VARCHAR, list_name VARCHAR, stage INTEGER,
  PRIMARY KEY (as_of, symbol, list_name));

CREATE TABLE IF NOT EXISTS fo_ban (as_of DATE, symbol VARCHAR, PRIMARY KEY (as_of, symbol));

CREATE TABLE IF NOT EXISTS deals (
  trade_date DATE, symbol VARCHAR, kind VARCHAR, client VARCHAR, side VARCHAR,
  qty BIGINT, price DOUBLE, PRIMARY KEY (trade_date, symbol, kind, client, side, qty, price));

CREATE TABLE IF NOT EXISTS announcements (
  symbol VARCHAR, ann_dt TIMESTAMP, subject VARCHAR, description VARCHAR,
  attachment_url VARCHAR, doc_id VARCHAR, PRIMARY KEY (symbol, ann_dt, subject));

CREATE TABLE IF NOT EXISTS documents (
  doc_id VARCHAR PRIMARY KEY, symbol VARCHAR, kind VARCHAR, title VARCHAR, period VARCHAR,
  url VARCHAR, local_path VARCHAR, text_path VARCHAR, sha256 VARCHAR, bytes BIGINT,
  pages INTEGER, fetched_at TIMESTAMP, visible_from DATE);

CREATE TABLE IF NOT EXISTS screener_meta (
  symbol VARCHAR PRIMARY KEY, basis VARCHAR, market_cap_cr DOUBLE, current_price DOUBLE,
  trailing_pe DOUBLE, book_value DOUBLE, dividend_yield_pct DOUBLE, roce_pct DOUBLE,
  roe_pct DOUBLE, high_52w DOUBLE, low_52w DOUBLE, industry VARCHAR, sector VARCHAR,
  fetched_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS fetch_log (
  run_id VARCHAR, source VARCHAR, key VARCHAR, status VARCHAR, http_status INTEGER,
  bytes BIGINT, started_at TIMESTAMP, ended_at TIMESTAMP, error VARCHAR);

CREATE TABLE IF NOT EXISTS quality_checks (
  run_id VARCHAR, as_of DATE, check_name VARCHAR, status VARCHAR, detail VARCHAR,
  checked_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS runs (
  run_id VARCHAR PRIMARY KEY, kind VARCHAR, started_at TIMESTAMP, ended_at TIMESTAMP,
  status VARCHAR, detail VARCHAR);

CREATE TABLE IF NOT EXISTS universe_monthly (
  as_of DATE, symbol VARCHAR, industry VARCHAR, close DOUBLE, adv20_inr DOUBLE,
  turnover_med120 DOUBLE, history_days INTEGER, PRIMARY KEY (as_of, symbol));

CREATE TABLE IF NOT EXISTS features (
  as_of DATE, symbol VARCHAR, industry VARCHAR, close DOUBLE, history_days INTEGER,
  mom_12_1 DOUBLE, mom_6_1 DOUBLE, mom_1 DOUBLE, vol_60 DOUBLE, vol_250 DOUBLE,
  dd_250 DOUBLE, dist_52w_high DOUBLE, dma50_ratio DOUBLE, dma200_ratio DOUBLE,
  atr14_pct DOUBLE, adv20_inr DOUBLE, turnover_med120 DOUBLE, vol_ratio_20_120 DOUBLE,
  deliv_pct_20 DOUBLE, deliv_ratio DOUBLE, amihud_60 DOUBLE, beta_250 DOUBLE,
  idio_vol_250 DOUBLE,
  sales_ttm DOUBLE, pat_ttm DOUBLE, sales_yoy_ttm DOUBLE, pat_yoy_ttm DOUBLE,
  sales_cagr_3y DOUBLE, pat_cagr_3y DOUBLE, opm_ttm DOUBLE, opm_chg_1y DOUBLE,
  roe DOUBLE, roce DOUBLE, debt_equity DOUBLE, int_cover DOUBLE, accruals DOUBLE,
  fcf_ttm DOUBLE, promoter_pct DOUBLE, promoter_chg_1y DOUBLE, inst_chg_1y DOUBLE,
  f_score DOUBLE, f_known DOUBLE, altman_zpp DOUBLE, stmt_age_days DOUBLE,
  shares_cr DOUBLE, mcap_cr DOUBLE, pe_ttm DOUBLE, pb DOUBLE, ps DOUBLE,
  earnings_yield DOUBLE, fcf_yield DOUBLE, div_yield DOUBLE,
  z_quality DOUBLE, z_value DOUBLE, z_momentum DOUBLE, z_lowrisk DOUBLE,
  buckets_known INTEGER, in_asm INTEGER, in_gsm INTEGER, in_fo_ban INTEGER,
  rankable INTEGER, PRIMARY KEY (as_of, symbol));

CREATE TABLE IF NOT EXISTS ranks (
  as_of DATE, sleeve VARCHAR, symbol VARCHAR, rank INTEGER, score DOUBLE, weight DOUBLE,
  regime VARCHAR, universe_size INTEGER, detail VARCHAR,
  PRIMARY KEY (as_of, sleeve, symbol));

CREATE TABLE IF NOT EXISTS regime_daily (
  trade_date DATE PRIMARY KEY, nifty500 DOUBLE, dma200 DOUBLE, vix DOUBLE,
  vix_pct DOUBLE, regime VARCHAR, exposure DOUBLE);

CREATE TABLE IF NOT EXISTS backtests (
  run_id VARCHAR PRIMARY KEY, sleeve VARCHAR, start_date DATE, end_date DATE,
  params VARCHAR, metrics VARCHAR, acceptance VARCHAR, verdict VARCHAR,
  created_at TIMESTAMP, report_path VARCHAR);

CREATE TABLE IF NOT EXISTS dossiers (
  symbol VARCHAR, as_of DATE, model VARCHAR, rating VARCHAR, confidence DOUBLE,
  json VARCHAR, markdown VARCHAR, created_at TIMESTAMP, PRIMARY KEY (symbol, as_of));

CREATE TABLE IF NOT EXISTS holidays (trade_date DATE PRIMARY KEY, note VARCHAR, seen_at TIMESTAMP);

CREATE TABLE IF NOT EXISTS factor_anomalies (
  symbol VARCHAR, ex_date DATE, factor DOUBLE, kind VARCHAR, reason VARCHAR, PRIMARY KEY (symbol, ex_date));

CREATE TABLE IF NOT EXISTS etf_list (symbol VARCHAR PRIMARY KEY, underlying VARCHAR, listing_date DATE, as_of DATE);

-- Phase 1: XBRL statements (Ind-AS results filings). Values in INR crore after scaling; first-seen wins.
CREATE TABLE IF NOT EXISTS statements_xbrl (
  symbol VARCHAR, basis VARCHAR, period_end DATE, period_start DATE, kind VARCHAR,       -- kind: D (duration) | I (instant)
  period_kind VARCHAR, tag VARCHAR, item VARCHAR, dims_key VARCHAR, value DOUBLE, text_value VARCHAR,
  unit VARCHAR, taxonomy VARCHAR, filing_dt TIMESTAMP, fetched_at TIMESTAMP, as_of DATE, visible_from DATE,
  PRIMARY KEY (symbol, basis, period_end, kind, tag, dims_key));
CREATE TABLE IF NOT EXISTS statements_xbrl_revisions (
  symbol VARCHAR, basis VARCHAR, period_end DATE, kind VARCHAR, tag VARCHAR, dims_key VARCHAR,
  value DOUBLE, text_value VARCHAR, filing_dt TIMESTAMP, fetched_at TIMESTAMP, source_url VARCHAR,
  PRIMARY KEY (symbol, basis, period_end, kind, tag, dims_key, fetched_at));
CREATE TABLE IF NOT EXISTS xbrl_filings (
  symbol VARCHAR, period_end DATE, basis VARCHAR, xbrl_url VARCHAR, filing_dt TIMESTAMP, taxonomy VARCHAR,
  status VARCHAR, facts INTEGER, rounding VARCHAR, scale_to_cr DOUBLE, scale_inferred BOOLEAN, is_bank BOOLEAN,
  revised BOOLEAN, seq_id VARCHAR, sha256 VARCHAR, bytes BIGINT, fetched_at TIMESTAMP, error VARCHAR,
  PRIMARY KEY (symbol, period_end, basis, xbrl_url));

-- Phase 1: filings
CREATE TABLE IF NOT EXISTS credit_ratings (
  app_id VARCHAR, symbol VARCHAR, company_name VARCHAR, isin VARCHAR, agency VARCHAR,
  rating_raw VARCHAR, rating VARCHAR, notch INTEGER, term VARCHAR, outlook VARCHAR, action VARCHAR,
  prev_rating VARCHAR, prev_notch INTEGER, prev_outlook VARCHAR, prev_dt DATE, rating_dt DATE,
  broadcast_dt TIMESTAMP, xbrl_url VARCHAR, fetched_at TIMESTAMP, as_of DATE, visible_from DATE,
  PRIMARY KEY (app_id));
CREATE TABLE IF NOT EXISTS board_meetings (
  symbol VARCHAR, meeting_dt DATE, purpose VARCHAR, description VARCHAR, kind VARCHAR,          -- kind: results | dividend | fund_raise | other
  intimation_dt TIMESTAMP, attachment_url VARCHAR, fetched_at TIMESTAMP, as_of DATE, visible_from DATE,
  PRIMARY KEY (symbol, meeting_dt, purpose));
CREATE TABLE IF NOT EXISTS insider_trades (
  symbol VARCHAR, disclosure_id VARCHAR, person VARCHAR, category VARCHAR, security_type VARCHAR, mode VARCHAR,
  side VARCHAR, qty BIGINT, value_inr DOUBLE, pre_pct DOUBLE, post_pct DOUBLE, from_dt DATE, to_dt DATE,
  intimation_dt DATE, broadcast_dt TIMESTAMP, regulation VARCHAR, xbrl_url VARCHAR, fetched_at TIMESTAMP,
  as_of DATE, visible_from DATE, PRIMARY KEY (symbol, disclosure_id));
CREATE TABLE IF NOT EXISTS holders_named (
  symbol VARCHAR, period_end DATE, category VARCHAR, holder VARCHAR, holder_kind VARCHAR,       -- person | entity | trust | government | institution
  shares BIGINT, pct DOUBLE, pledged_shares BIGINT, pledged_pct DOUBLE, locked_shares BIGINT,
  source_url VARCHAR, fetched_at TIMESTAMP, as_of DATE, visible_from DATE,
  PRIMARY KEY (symbol, period_end, category, holder));
CREATE TABLE IF NOT EXISTS pledges (
  symbol VARCHAR, period_end DATE, source VARCHAR, promoter_shares BIGINT, promoter_pledged_shares BIGINT,
  pledged_pct_of_promoter DOUBLE, pledged_pct_of_total DOUBLE, encumbered_other_flag BOOLEAN,
  fetched_at TIMESTAMP, as_of DATE, visible_from DATE, PRIMARY KEY (symbol, period_end, source));

-- Phase 4: documents
CREATE TABLE IF NOT EXISTS doc_sections (
  doc_id VARCHAR, section_kind VARCHAR, seq INTEGER, page_start INTEGER, page_end INTEGER, heading VARCHAR,
  text VARCHAR, tables_json VARCHAR, chars INTEGER, method VARCHAR, confidence DOUBLE, parser_version VARCHAR,
  created_at TIMESTAMP, PRIMARY KEY (doc_id, section_kind, seq));

-- Phase 2: metrics (long format, one row per metric, PIT as-of)
CREATE TABLE IF NOT EXISTS fund_metrics (
  as_of DATE, symbol VARCHAR, metric VARCHAR, value DOUBLE, status VARCHAR, unit VARCHAR,
  source_table VARCHAR, source_keys VARCHAR, inputs_as_of DATE, note VARCHAR, engine_version VARCHAR,
  PRIMARY KEY (as_of, symbol, metric));

-- Phase 5: graph (edge identity = src,type,dst,evidence; lanes = derived_by)
CREATE TABLE IF NOT EXISTS graph_nodes (
  id VARCHAR PRIMARY KEY, kind VARCHAR, name VARCHAR, attrs_json VARCHAR, as_of DATE,
  derived_by VARCHAR, first_seen_at TIMESTAMP, updated_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS graph_edges (
  src VARCHAR, type VARCHAR, dst VARCHAR, evidence VARCHAR, valid_from DATE, valid_to DATE,
  confidence DOUBLE, derived_by VARCHAR, attrs_json VARCHAR, as_of DATE, visible_from DATE, created_at TIMESTAMP,
  PRIMARY KEY (src, type, dst, evidence));
CREATE TABLE IF NOT EXISTS graph_aliases (alias VARCHAR PRIMARY KEY, node_id VARCHAR, note VARCHAR, added_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS graph_features (
  as_of DATE, symbol VARCHAR, group_id VARCHAR, group_size INTEGER, group_pledge_max DOUBLE,
  group_surveillance INTEGER, group_downgrades_12m INTEGER, auditor VARCHAR, auditor_clients INTEGER,
  auditor_qualified_share_24m DOUBLE, auditor_small INTEGER, sector_downgrade_share_12m DOUBLE,
  status VARCHAR, PRIMARY KEY (as_of, symbol));

-- Phase 3: rating
CREATE TABLE IF NOT EXISTS ratings (
  symbol VARCHAR, as_of DATE, engine_version VARCHAR, variant VARCHAR, status VARCHAR, rating VARCHAR,
  score DOUBLE, confidence DOUBLE, confidence_band VARCHAR, er_lo DOUBLE, er_mid DOUBLE, er_hi DOUBLE,
  coverage DOUBLE, pillars_json VARCHAR, gates_json VARCHAR, manifest_json VARCHAR, manifest_sha VARCHAR,
  data_errors_json VARCHAR, created_at TIMESTAMP, PRIMARY KEY (symbol, as_of, engine_version, variant));
CREATE TABLE IF NOT EXISTS rating_ledger (
  symbol VARCHAR, as_of DATE, engine_version VARCHAR, published_at TIMESTAMP, rating VARCHAR, score DOUBLE,
  confidence DOUBLE, close_at_publish DOUBLE, horizon_days INTEGER, matured_at DATE, fwd_return DOUBLE,
  bench_return DOUBLE, excess_return DOUBLE, outcome VARCHAR,                                  -- outcome: pending | hit | miss | delisted
  PRIMARY KEY (symbol, as_of, engine_version));
CREATE TABLE IF NOT EXISTS rating_calibrations (
  run_id VARCHAR PRIMARY KEY, engine_version VARCHAR, start_date DATE, end_date DATE, holdout_start DATE,
  n_obs INTEGER, metrics_json VARCHAR, acceptance_json VARCHAR, verdict VARCHAR, report_path VARCHAR, created_at TIMESTAMP);

-- Phase 6: research
CREATE TABLE IF NOT EXISTS research_runs (
  run_id VARCHAR PRIMARY KEY, symbol VARCHAR, as_of DATE, mode VARCHAR, model VARCHAR, status VARCHAR,
  passes_json VARCHAR, input_tokens BIGINT, output_tokens BIGINT, cache_read_tokens BIGINT, cost_usd DOUBLE,
  batch_id VARCHAR, custom_id VARCHAR, dossier_version INTEGER, started_at TIMESTAMP, ended_at TIMESTAMP, error VARCHAR);
CREATE TABLE IF NOT EXISTS dossier_claims (
  symbol VARCHAR, as_of DATE, claim_id VARCHAR, section VARCHAR, text VARCHAR, citations_json VARCHAR,
  quote VARCHAR, table_ref_json VARCHAR, verified BOOLEAN, verify_method VARCHAR, verify_score DOUBLE,
  verifier_note VARCHAR, run_id VARCHAR, PRIMARY KEY (symbol, as_of, claim_id));
CREATE TABLE IF NOT EXISTS web_sources (
  src_id VARCHAR PRIMARY KEY, symbol VARCHAR, run_id VARCHAR, url VARCHAR, title VARCHAR, published DATE,
  source_kind VARCHAR, sha256 VARCHAR, text_path VARCHAR, fetched_at TIMESTAMP, as_of DATE, visible_from DATE);
CREATE TABLE IF NOT EXISTS news_items (
  symbol VARCHAR, sha1 VARCHAR, published DATE, title VARCHAR, source VARCHAR, url VARCHAR, fetched_at TIMESTAMP,
  as_of DATE, visible_from DATE, PRIMARY KEY (symbol, sha1));
