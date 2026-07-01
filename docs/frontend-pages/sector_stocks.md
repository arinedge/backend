# Sector Stocks Page — Frontend Design Reference

## Purpose
A page that groups stocks by sector (e.g. Financial Services, Technology, Healthcare). Users browse sectors to discover peer companies or find investment opportunities within a sector.

## URL Pattern
`/sectors` — master list of all sectors  
`/sectors/{sector-slug}` — stocks within a specific sector

## Data Source
- **Primary:** `stock_info.data->>'sector'` — Yahoo Finance sector classification (1,753+ stocks with sector data)
- **Fallback:** `yfinance` live fetch for stocks missing from `stock_info`
- **Canonical entities:** `nse_canonical_entities.sector` for resolver-provided sector

All sector/industry enrichment is handled by the comparison API automatically.

## API Endpoints Needed

### `GET /api/sectors` — List all sectors with stock counts and aggregate stats

```json
{
  "sectors": [
    {
      "slug": "financial-services",
      "name": "Financial Services",
      "stock_count": 185,
      "avg_pe": 18.5,
      "avg_roe": 14.2,
      "avg_market_cap": 45000000000000,
      "top_stocks": ["SBIN", "ICICIBANK", "HDFCBANK", "AXISBANK", "KOTAKBANK"]
    }
  ],
  "total_sectors": 12,
  "total_stocks": 1753
}
```

### `GET /api/sectors/{sector-slug}` — Stocks within a sector

```json
{
  "sector": {
    "slug": "financial-services",
    "name": "Financial Services",
    "stock_count": 185
  },
  "stocks": [
    {
      "symbol": "SBIN",
      "company_name": "State Bank of India",
      "slug": "sbin",
      "pe": 11.14,
      "market_cap": 9371846180864,
      "price_change_1d": 1.25,
      "is_fno": true
    }
  ],
  "aggregate": {
    "avg_pe": 18.5,
    "avg_roe": 14.2,
    "avg_market_cap": 45000000000000,
    "total_fno_stocks": 45
  }
}
```

## Page Layout — Sector List (`/sectors`)

```
+------------------------------------------------------------+
|  Browse by Sector                                         |
|  1,753 stocks across 12 sectors                           |
+------------------------------------------------------------+
| +------------------+  +------------------+  +-----------+  |
| | Financial Svc    |  | Technology       |  | Healthcare |  |
| | 185 stocks       |  | 126 stocks       |  | 126 stocks |  |
| | Avg PE: 18.5     |  | Avg PE: 28.1     |  | Avg PE: 32 |  |
| | [View →]         |  | [View →]         |  | [View →]   |  |
| +------------------+  +------------------+  +-----------+  |
| +------------------+  +------------------+  +-----------+  |
| | Consumer Cycl.   |  | Industrials      |  | Basic Mat. |  |
| | 324 stocks       |  | 362 stocks       |  | 276 stocks |  |
| | Avg PE: 22.3     |  | Avg PE: 32.4     |  | Avg PE: 18 |  |
| | [View →]         |  | [View →]         |  | [View →]   |  |
| +------------------+  +------------------+  +-----------+  |
+------------------------------------------------------------+
```

## Page Layout — Sector Detail (`/sectors/{slug}`)

```
+------------------------------------------------------------+
| Financial Services                                         |
| 185 stocks · Avg PE 18.5 · Avg ROE 14.2%                  |
+------------------------------------------------------------+
| [Sort: Market Cap ▼] [Filter: F&O Only] [Search...]       |
+------------------------------------------------------------+
| Symbol | Company              | PE  | MCap (Cr) | 1D%  | F&O |
|--------+----------------------+-----+-----------+------+-----|
| SBIN   | State Bank of India  | 11.1| 937,184   | +1.2 |  ✓  |
| HDFCB  | HDFC Bank            | 18.2| 1,250,000 | -0.5 |  ✓  |
| ICICI  | ICICI Bank           | 17.7| 951,665   | +0.8 |  ✓  |
| ...    | ...                  | ... | ...       | ...  | ... |
+------------------------------------------------------------+
| [Load More — 150 more stocks]                              |
+------------------------------------------------------------+
```

## SEO
- Each sector gets an SEO page at `/sectors/{slug}` with meta description listing stock count and top companies
- Title pattern: `{sector} Stocks — Financials, F&O, Valuation | ArinEdge`
- Sitemap entry for each sector page
- Breadcrumb: `Home > Sectors > {sector}`

## Implementation Notes
- Sector slugs follow `_slugify()` from `stock_compare_service.py:95` (lowercase, remove special chars, replace spaces with hyphens)
- Data for sector pages would come from a new API endpoint (not yet implemented)
- Existing `stock_info` table already has sector data; FYI Finance classification is used
- FNO filter toggles between all stocks and only F&O-traded stocks
- Market cap in Crores (Indian convention) for display
