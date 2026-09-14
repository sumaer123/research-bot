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
