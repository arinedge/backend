# Stock Compare API Design

## Scope

This document describes the backend comparison API for `/api/compare/stocks`.
The repository was inspected from the SQLAlchemy models, migration files, and
existing service/routes. A live database reflection pass was attempted from the
workspace, but the remote PostgreSQL host is not reachable from this sandbox.
This report therefore distinguishes between:

- Tables confirmed in the source tree
- Tables referenced by the request but not present in the codebase
- Tables that may exist in the live database but could not be verified here

## 1. Tables Discovered

### Confirmed in models/migrations

- `users`
- `brokers`
- `waitlist_entries`
- `market_data`
- `market_status`
- `market_holidays`
- `market_timings`
- `market_news`
- `news_extraction` (`public.news_extraction`)
- `fno_symbols`
- `fno_expiries`
- `fno_instruments`
- `nse_canonical_entities`
- `nse_entity_aliases`
- `nse_entity_embeddings`
- `nse_entity_resolution_log`
- `nse_event_types`
- `nse_events`
- `nse_relationships`
- `nse_relationship_evidence`
- `nse_graph_metrics`
- `nse_propagation_scores`
- `service_registry`
- `service_runs`
- `table_metadata`

### Referenced by the request but not confirmed in this codebase

- `stock_info`
- `stock_prices`
- `stock_financials`
- `stock_holders`
- `stock_analysis`
- `stock_earnings_dates`
- `stock_insider_transactions`
- `daily_stock_metrics`
- `daily_factor_metrics`
- `daily_stock_scores`
- `daily_stock_rankings`
- `scanner_results`
- `option_chain_snapshots`
- `option_contracts`
- `nexus_option_snapshots`
- `nexus_events`
- `nexus_signal_instances`
- `nexus_anomaly_scores`
- `nexus_regime_snapshots`
- `fii_activity`
- `dii_activity`
- `participant_open_interest`
- `participant_oi`
- `category_turnover_cash`
- `category_turnover_fo`

## 2. Fields Available Per Table

### `nse_canonical_entities`

- `id`
- `canonical_name`
- `entity_type`
- `sector`
- `ticker`
- `isin`
- `description`
- `metadata`
- `confidence`
- `created_at`
- `updated_at`

### `nse_entity_aliases`

- `id`
- `canonical_id`
- `alias`
- `alias_type`
- `confidence`
- `source`
- `first_seen_at`
- `last_seen_at`

### `nse_entity_resolution_log`

- `id`
- `extraction_id`
- `raw_name`
- `resolved_id`
- `confidence`
- `method`
- `created_at`

### `nse_relationships`

- `id`
- `source_entity`
- `target_entity`
- `relation_type`
- `weight`
- `confidence`
- `first_seen_at`
- `last_seen_at`
- `source_count`
- `metadata`

### `nse_graph_metrics`

- `entity_id`
- `pagerank`
- `degree_centrality`
- `betweenness`
- `mention_velocity`
- `sentiment_score`
- `sentiment_velocity`
- `cluster_id`
- `computed_at`

### `nse_events`

- `id`
- `extraction_id`
- `news_id`
- `event_type_id`
- `event_type_raw`
- `sentiment`
- `confidence`
- `importance`
- `evidence_span`
- `event_date`
- `article_date`
- `metadata`
- `created_at`

### `market_news`

- `id`
- `guid`
- `title`
- `link`
- `description`
- `author`
- `category`
- `image_url`
- `source_name`
- `source_url`
- `feed_url`
- `published_at`
- `raw_pub_date`
- `created_at`
- `hash_id`
- `raw_data`

### `market_data`

- `id`
- `instrument_key`
- `symbol`
- `name`
- `last_price`
- `change`
- `change_percent`
- `open_price`
- `high_price`
- `low_price`
- `close_price`
- `volume`
- `bid`
- `ask`
- `oi`
- `oi_change`
- `iv`
- `delta`
- `gamma`
- `theta`
- `vega`
- `rho`
- `source`
- `fetched_at`
- `created_at`

### `fno_symbols`

- `id`
- `symbol`
- `name`
- `segment`
- `exchange`
- `asset_type`
- `underlying_key`
- `lot_size`
- `tick_size`
- `freeze_quantity`
- `minimum_lot`
- `qty_multiplier`
- `weekly`
- `is_active`
- `created_at`

### `fno_expiries`

- `id`
- `symbol_id`
- `expiry_date`
- `expiry_timestamp`
- `weekly`
- `is_active`
- `created_at`

### `fno_instruments`

- `id`
- `symbol_id`
- `expiry_id`
- `instrument_key`
- `exchange_token`
- `trading_symbol`
- `instrument_type`
- `strike_price`
- `lot_size`
- `tick_size`
- `freeze_quantity`
- `minimum_lot`
- `qty_multiplier`
- `asset_type`
- `underlying_type`
- `underlying_symbol`
- `asset_symbol`
- `underlying_key`
- `asset_key`
- `name`
- `segment`
- `exchange`
- `weekly`
- `is_active`
- `created_at`

### `service_runs` / `table_metadata`

- Operational metadata only
- Useful for freshness checks and batch-run tracing

## 3. Fields Usable For Comparison

- Identity resolution: `canonical_name`, `ticker`, `isin`, `alias`, `entity_type`, `sector`
- Graph/context: `nse_relationships`, `nse_graph_metrics`, `nse_events`
- News: `market_news`, `news_extraction`
- Market/price context: `market_data`
- F&O context: `fno_symbols`, `fno_expiries`, `fno_instruments`
- Operational freshness: `service_runs`, `table_metadata`

## 4. Missing Tables / Fields

The codebase does not currently define the financial-statement and analytics tables
required by the request, including:

- `stock_financials`
- `stock_prices`
- `stock_holders`
- `stock_insider_transactions`
- `daily_stock_metrics`
- `daily_factor_metrics`
- `daily_stock_scores`
- `daily_stock_rankings`
- `scanner_results`
- `option_chain_snapshots`
- `nexus_*` signal/anomaly/regime tables
- `fii_activity`, `dii_activity`, `participant_*`, turnover tables

As a result:

- Financial snapshot, ratio, holding, insider, scanner, and nexus sections are
  returned as partial or missing unless equivalent live tables exist outside the
  current source tree.
- The comparison API must not fabricate values for these sections.

## 5. API Schema

### Query endpoint

- `GET /api/compare/stocks?stock1=maruti&stock2=indiamart`

### Path endpoint

- `GET /api/compare/stocks/{stock1}/vs/{stock2}`

### Success response

- `resolved: true`
- `request`
- `canonical`
- `stock1`
- `stock2`
- `seo`
- `summary`
- `sections`
- `tables`
- `charts`
- `related_links`
- `data_quality`
- `seo_eligibility`

### Error response

- `resolved: false`
- `request`
- `errors`
- `suggestions`
- `seo_eligibility`

## 6. Query Strategy

1. Resolve both inputs without mutating the database.
2. Prefer exact matches against:
   - canonical ticker
   - canonical name
   - canonical slug-derived variants
   - entity aliases
   - F&O symbol table
   - market data symbol
   - optional reflected stock tables if present
3. Return suggestions only when the input is unresolved or ambiguous.
4. Build comparison sections only from available data.
5. Limit news and event rows to the most recent few items.
6. Use `market_data` history for price and volatility context when no dedicated
   `stock_prices` table is available.
7. Avoid N+1 patterns by fetching per-section in bounded queries.

## 7. Data Quality Rules

- Never generate fake rows or metrics.
- Use `missing` status when a table or column does not exist.
- Use `partial` when some but not all metrics are available.
- Use `limited` when only identity-level context exists.
- Compute `completeness_score` from available section coverage.
- Prefer ISO timestamps for freshness fields.
- Convert NaN and infinity to null.

## 8. SEO Eligibility Rules

Indexable only when:

- both stocks resolve
- identity exists for both sides
- at least 3 useful sections are available
- the summary is non-generic
- the page does not depend on loading-only content

Noindex when:

- one or both stocks are unresolved
- the same stock is compared to itself
- the comparison is mostly empty
- the canonical target is ambiguous or mismatched

## 9. Performance / Index Recommendations

- `nse_entity_aliases(alias)` should stay indexed for resolution.
- Add or keep composite indexes on:
  - `nse_relationships(source_entity, target_entity)`
  - `nse_events(news_id, extraction_id)`
  - `market_data(symbol, fetched_at)`
  - `fno_instruments(underlying_symbol, expiry_id, instrument_type)`
- Add a partial index for active F&O symbols if lookups grow.
- If financial tables are introduced later, index by:
  - `symbol`
  - `fiscal_period`
  - `reporting_date`
- Cache resolution for 24h, price context for 15m-1h, event/news for 15m-1h,
  and options for 5m-15m.

## 10. Implementation Notes

- Router mounted at `/api/compare`
- Both endpoint forms call the same comparison service
- Resolver is non-mutating
- Comparison output is structured for frontend rendering and SEO metadata
- All unavailable sections are returned explicitly with missing flags

