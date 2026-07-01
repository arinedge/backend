# Industry Stocks Page — Frontend Design Reference

## Purpose
A page that groups stocks by fine-grained industry (e.g. Banks - Regional, Software - Application, Specialty Chemicals). More precise than sector pages — ideal for direct peer comparisons.

## URL Pattern
`/industries` — master list of all industries  
`/industries/{industry-slug}` — stocks within a specific industry

## Data Source
- **Primary:** `stock_info.data->>'industry'` — Yahoo Finance industry classification (1,300+ stocks with industry data)
- **Fallback:** `yfinance` live fetch for stocks missing from `stock_info`

## API Endpoints Needed

### `GET /api/industries` — List all industries grouped by sector

```json
{
  "industries": [
    {
      "slug": "banks-regional",
      "name": "Banks - Regional",
      "sector": "Financial Services",
      "stock_count": 34,
      "avg_pe": 16.2,
      "avg_roe": 13.8,
      "avg_market_cap": 52000000000000,
      "top_stocks": ["SBIN", "ICICIBANK", "HDFCBANK", "AXISBANK", "KOTAKBANK"]
    },
    {
      "slug": "software-application",
      "name": "Software - Application",
      "sector": "Technology",
      "stock_count": 25,
      ...
    }
  ],
  "grouped_by_sector": {
    "Financial Services": {
      "stock_count": 185,
      "industries": ["Banks - Regional", "Capital Markets", "Credit Services", ...]
    },
    "Technology": {
      "stock_count": 126,
      "industries": ["Software - Application", "Information Technology Services", ...]
    }
  }
}
```

### `GET /api/industries/{industry-slug}` — Stocks within an industry

```json
{
  "industry": {
    "slug": "banks-regional",
    "name": "Banks - Regional",
    "sector": "Financial Services",
    "stock_count": 34
  },
  "stocks": [
    {
      "symbol": "SBIN",
      "company_name": "State Bank of India",
      "slug": "sbin",
      "pe": 11.14,
      "market_cap": 9371846180864,
      "price_change_1d": 1.25,
      "roe": 15.48,
      "net_margin": 22.11,
      "is_fno": true
    }
  ],
  "aggregate": {
    "avg_pe": 16.2,
    "avg_roe": 13.8,
    "avg_net_margin": 18.5,
    "avg_market_cap": 52000000000000,
    "total_fno_stocks": 22
  }
}
```

## Page Layout — Industry List (`/industries`)

```
+------------------------------------------------------------+
| Browse by Industry                                         |
| 1,300+ stocks across 80+ industries grouped by sector     |
+------------------------------------------------------------+
| Financial Services (185 stocks)                            |
|  ├─ Banks - Regional .............. 34 stocks              |
|  ├─ Capital Markets ............... 47 stocks              |
|  ├─ Credit Services ............... 45 stocks              |
|  └─ ... (3 more)                                          |
|                                                            |
| Technology (126 stocks)                                    |
|  ├─ Information Technology Services  51 stocks             |
|  ├─ Software - Application ....... 25 stocks               |
|  ├─ Software - Infrastructure .... 12 stocks               |
|  └─ ... (2 more)                                          |
|                                                            |
| Healthcare (126 stocks)                                    |
|  ├─ Drug Manufacturers - Specialty  65 stocks              |
|  ├─ Medical Devices .............. 18 stocks               |
|  ├─ Medical Instruments ......... 12 stocks                |
|  └─ ... (3 more)                                          |
+------------------------------------------------------------+
| [Expanded View]  [Collapsed View]                          |
+------------------------------------------------------------+
```

## Page Layout — Industry Detail (`/industries/{slug}`)

```
+------------------------------------------------------------+
| Banks - Regional                                           |
| 34 stocks in Financial Services · Avg PE 16.2              |
+------------------------------------------------------------+
| [Sort: Market Cap ▼] [Filter: F&O Only] [Search...]       |
+------------------------------------------------------------+
| Symbol | Company              | PE  | ROE% | N.Margin | F&O |
|--------+----------------------+-----+------+----------+-----|
| HDFCB  | HDFC Bank            | 18.2| 16.5 |  24.3    |  ✓  |
| ICICI  | ICICI Bank           | 17.7| 16.4 |  24.9    |  ✓  |
| SBIN   | State Bank of India  | 11.1| 15.5 |  22.1    |  ✓  |
| AXIS   | Axis Bank            | 14.5| 14.2 |  20.8    |  ✓  |
| KOTAK  | Kotak Mahindra       | 19.8| 12.8 |  26.1    |  ✓  |
| ...    | ...                  | ... | ...  |  ...      | ... |
+------------------------------------------------------------+
| Click any row to → Compare with peer                       |
| Select two rows → Direct peer comparison                  |
+------------------------------------------------------------+
```

## Direct Peer Comparison Entry Point
The industry page is the primary entry point for **direct_peer** comparisons. When a user selects two stocks from the same industry:

1. Click "Compare" → navigates to `/compare/{stock1-slug}-vs-{stock2-slug}`
2. The comparison API recognizes they're in the same industry → `comparison_type: "direct_peer"`
3. Frontend highlights industry-specific metrics (ROE, NIM, cost-income ratio for banks; ARR, churn for SaaS)

## SEO
- Each industry gets an SEO page at `/industries/{slug}`
- Title pattern: `{industry} Stocks — Peer Comparison, Financials & F&O | ArinEdge`
- Breadcrumb: `Home > Industries > {sector} > {industry}`
- Industry pages are higher value for SEO than sector pages (more specific, lower competition)
- Internal linking from industry pages to comparison pages drives engagement

## Implementation Notes
- Industry slugs follow `_slugify()` — e.g. "Banks - Regional" → `banks-regional`
- Same API backend as sector pages — differentiate via filter parameter
- Industry detail page should show comparison CTA prominently (this is where users are most likely to compare)
- ROE and Net Margin columns are industry-specific — adjust columns per industry type (e.g. show NIM for banks, ARR growth for SaaS)
- Market cap in Crores for Indian display convention
