# Stock Comparison Overhaul

## Problem

The existing `GET /api/compare/stocks?stock1=X&stock2=Y` endpoint is broken and slow:
- `stock_financials` is EAV (`line_item`/`value`) but code assumes wide columns → financials/cashflow return empty
- Ticker format mismatch: resolver returns `SBIN` but financial tables use `SBIN.NS`
- FNO section ignores `nexus_option_snapshots` (net_gamma, strike_details)
- Rich tables unused: `stock_info` (comprehensive JSON), `stock_holders`, `stock_analysis`, `stock_earnings_dates`
- Response has 25+ sections with generic "data is limited" noise
- N+1 queries, slow resolution

## Solution

Rewrite `stock_compare_service.py` as a focused service that:

### Endpoint (unchanged)
`GET /api/compare/stocks?stock1=sbin&stock2=icicibank`
`GET /api/compare/stocks/{stock1}/vs/{stock2}`

### Output Structure (two-tier)

```
{
  "resolved": true,
  "request": { "stock1_input": "sbin", "stock2_input": "icicibank" },
  "stock1": { ... identity ... },
  "stock2": { ... identity ... },
  "core": {
    "identity": { symbol, company_name, sector, industry, market_cap, is_fno, slug },
    "price_performance": { 1D, 1W, 1M, 3M, 6M, 1Y returns, 52W high/low, latest close },
    "financials": { Revenue, Net Income, EPS, Total Assets, Total Debt, Cash, Interest Income, Interest Expense, Net Interest Income, Operating Revenue },
    "cash_flow": { Operating CF, Free CF, CapEx, Dividends Paid, Financing CF, Investing CF },
    "valuation": { PE, PB, EV/EBITDA, EV/Sales, PEG — from stock_info JSON },
    "profitability": { ROE, ROA, Net Margin, Operating Margin, Gross Margin — from stock_info JSON },
    "growth": { Revenue Growth %, Earnings Growth %, EPS Growth % — from stock_info JSON },
    "holders": { Promoter %, FII %, DII %, Mutual Fund %, Public % — from stock_holders },
    "fno": {
      is_fno, spot_price, expiry, days_to_expiry,
      net_gamma, total_gamma, gamma_flip_points,
      pcr_oi (computed from strike_details: total_put_oi/total_call_oi),
      pcr_volume (computed from strike_details),
      max_pain (from nexus_expiry_intel),
      top_oi_strikes (top 5 by OI for CE and PE),
      strike_count
    },
    "analysis": { bull_case, bear_case, red_flags, investment_thesis, confidence_score — from stock_analysis },
    "summary": { comparison_type, text }
  },
  "detail": {
    "balance_sheet": { Assets, Liabilities, Equity detail from financials EAV },
    "insider_activity": { recent transactions },
    "earnings": { upcoming date, last 4 quarters EPS surprise % — from stock_earnings_dates },
    "options_detail": { per-strike gamma/iv/oi/delta for near-expiry },
    "entity_graph": { graph metrics, related entities — from nse_graph_metrics },
    "fii_dii_activity": { FII/DII net buy/sell — from fii_activity/dii_activity },
    "news": { recent articles, counts — from market_news }
  },
  "data_quality": { completeness_score, available_sections, warnings },
  "cached_at": "...",
  "expires_at": "..."
}
```

### Data Sources

| Section | Primary Source | Notes |
|---------|---------------|-------|
| identity | `nse_canonical_entities` + `fno_symbols` | Existing resolver, add `.NS` to ticker for finance tables |
| price_performance | `stock_prices` (OHLCV, `.NS` ticker) | Calculate returns: 1D/1W/1M/3M/6M/1Y, 52W high/low |
| financials | `stock_financials` (EAV pivot) | Pivot `line_item` → column for: Total Revenue, Net Income, Basic EPS, Total Assets, Total Debt, Cash And Cash Equivalents, Interest Income, Interest Expense, Net Interest Income, Operating Revenue |
| cash_flow | `stock_financials` WHERE statement_type=cashflow | Operating Cash Flow, Free Cash Flow, Capital Expenditure, Cash Dividends Paid, Financing Cash Flow, Investing Cash Flow |
| valuation/profitability/growth | `stock_info.json` | PE, PB, EV/EBITDA, ROE, ROA, Net Margin, Operating Margin, Revenue Growth, Earnings Growth — all pre-computed by Yahoo Finance |
| holders | `stock_holders` | Aggregate by holder_type, sum percent_held |
| fno | `nexus_option_snapshots.strike_details` + `nexus_expiry_intel` | Compute PCR OI from strike_details JSON array, derive ATM IV from strikes nearest to spot |
| analysis | `stock_analysis.summary` (JSON) | bull_case, bear_case, red_flags, investment_thesis, confidence_score |
| insider | `stock_insider_transactions` | Last 10 transactions per stock |
| earnings | `stock_earnings_dates` | Last 4 quarters: eps_estimate, eps_actual, surprise_pct |
| options_detail | `nexus_option_snapshots.strike_details` | Pass through strike_details for analysis |
| news | `market_news` | Recent news count and headlines |

### FNO Metrics Computation

From `nexus_option_snapshots.strike_details` (JSON array):
- **PCR OI** = sum(put_oi) / sum(call_oi) across all strikes
- **ATM IV** = average of CE and PE IV where strike is closest to spot_price
- **Top OI Strikes** = sort strikes by OI descending, return top 5 CE and PE
- **Gamma Exposure** = net_gamma (already computed)
- **Gamma Flip Points** = gamma_flip_points (already computed)

From `nexus_expiry_intel`:
- **Max Pain** = max_pain
- **Expected Range** = expected_range
- **Days to Expiry** = days_to_expiry

### Caching

Use existing `StockCompareCache` model with 7-day TTL. On cache hit, check `generated_at < now() - 7 days`. On miss, compute and save.

### Performance Improvements

1. **Batch resolution**: Resolve both stocks in parallel within a single session
2. **Single-pass EAV**: One query per stock for financials, pivot in Python
3. **stock_info JSON**: Avoids computing ratios from raw financials
4. **Skip empty tables**: Check table existence once, skip if absent
5. **Limit strike details**: Return top 20 strikes instead of all 82

### Files Changed

- `app/services/stock_compare_service.py` — Rewrite (remove 1795 lines, add ~800 lines)
- `app/api/comparison.py` — Minor updates to response model
- `app/schemas/compare.py` — Add core/detail response models
- `app/services/stock_resolver.py` — Add `.NS` ticker matching for finance tables

### Response Model

```python
class CoreComparison(BaseModel):
    identity: dict
    price_performance: dict
    financials: dict
    cash_flow: dict
    valuation: dict
    profitability: dict
    growth: dict
    holders: dict
    fno: dict
    analysis: dict | None
    summary: dict

class DetailComparison(BaseModel):
    balance_sheet: dict
    insider_activity: dict
    earnings: dict
    options_detail: dict
    entity_graph: dict
    fii_dii_activity: dict
    news: dict

class StockComparisonResponse(BaseModel):
    resolved: bool
    request: ComparisonRequest
    stock1: StockIdentity | None
    stock2: StockIdentity | None
    core: CoreComparison
    detail: DetailComparison | None
    data_quality: DataQuality
    cached_at: str | None
    expires_at: str | None
```
