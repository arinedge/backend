# Stock Comparison Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite /api/compare/stocks to return a clean two-tier JSON (core + detail) with proper financials, cashflow, FNO metrics, holders, and analysis — using existing database tables correctly.

**Architecture:** Rewrite StockCompareService to use stock_financials EAV pivot for financials/cashflow, stock_info JSON for valuation/profitability/growth, nexus_option_snapshots strike_details for FNO metrics, stock_holders for ownership, and stock_prices for performance. Two-tier output: core (always populated) + detail (optional extras). Cache via existing StockCompareCache model (7-day TTL).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, PostgreSQL, Pydantic v2

---

### Task 0: Read current files to understand existing patterns

**Files:**
- Read: `app/services/stock_compare_service.py`
- Read: `app/schemas/compare.py`
- Read: `app/api/comparison.py`
- Read: `app/models/compare.py`

- [ ] **Step 1: Read current comparison service**

Read `stock_compare_service.py` to understand existing patterns, method signatures, and the cache logic.

- [ ] **Step 2: Read schemas and API endpoint**

Read `schemas/compare.py` and `api/comparison.py` to understand existing response models.

- [ ] **Step 3: Read cache model**

Read `models/compare.py` to understand StockCompareCache fields.

---

### Task 1: Update Pydantic schemas for new response structure

**Files:**
- Modify: `app/schemas/compare.py`

- [ ] **Step 1: Add CoreComparison and DetailComparison models**

Add after the existing `StockComparisonResponse` class (or replace it):

```python
class CoreComparison(BaseModel):
    identity: dict[str, Any] = Field(default_factory=dict)
    price_performance: dict[str, Any] = Field(default_factory=dict)
    financials: dict[str, Any] = Field(default_factory=dict)
    cash_flow: dict[str, Any] = Field(default_factory=dict)
    valuation: dict[str, Any] = Field(default_factory=dict)
    profitability: dict[str, Any] = Field(default_factory=dict)
    growth: dict[str, Any] = Field(default_factory=dict)
    holders: dict[str, Any] = Field(default_factory=dict)
    fno: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] | None = None
    summary: dict[str, Any] = Field(default_factory=dict)

class DetailComparison(BaseModel):
    balance_sheet: dict[str, Any] = Field(default_factory=dict)
    insider_activity: dict[str, Any] = Field(default_factory=dict)
    earnings: dict[str, Any] = Field(default_factory=dict)
    options_detail: dict[str, Any] = Field(default_factory=dict)
    entity_graph: dict[str, Any] = Field(default_factory=dict)
    fii_dii_activity: dict[str, Any] = Field(default_factory=dict)
    news: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 2: Update StockComparisonResponse**

Replace the existing `StockComparisonResponse`:

```python
class StockComparisonResponse(BaseModel):
    resolved: bool = True
    request: ComparisonRequest
    canonical: dict[str, str] = Field(default_factory=dict)
    stock1: StockIdentity | None = None
    stock2: StockIdentity | None = None
    seo: dict[str, Any] = Field(default_factory=dict)
    core: CoreComparison = Field(default_factory=CoreComparison)
    detail: DetailComparison | None = None
    related_links: list[RelatedLink] = Field(default_factory=list)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    seo_eligibility: SeoEligibility = Field(default_factory=SeoEligibility)
    cached_at: str | None = None
    expires_at: str | None = None
```

---

### Task 2: Fix ticker resolution for `.NS` suffix tables

**Files:**
- Modify: `app/services/stock_compare_service.py` (StockResolverService)

- [ ] **Step 1: Add `.NS` suffix to resolved ticker**

In `StockResolverService.resolve_stock()`, after resolving a candidate, add a `.NS` variant for finance table lookups. Add an `exchange_ticker` field to `_ResolvedCandidate`:

```python
# In _ResolvedCandidate dataclass (after line 128):
exchange_ticker: str | None = None  # e.g. "SBIN.NS"

# In _entity_from_row after line 275:
exchange_ticker = f"{ticker}.NS" if ticker else None

# In _ResolvedCandidate init calls for other sources (fno, market_data, stock_info):
# Add exchange_ticker parameter where symbol is known
```

---

### Task 3: Rewrite compare service — data layer

**Files:**
- Modify: `app/services/stock_compare_service.py` (full rewrite)

- [ ] **Step 1: Write `_fetch_financials_eav()` method**

Pivot `stock_financials` EAV data for a specific ticker:

```python
def _fetch_financials_eav(self, ticker: str) -> dict[str, dict[str, Any]]:
    """Return {statement_type: {line_item: value}} for the latest fiscal_date."""
    table = self._get_table("stock_financials")
    if table is None:
        return {}
    columns = table.c
    rows = self.db.execute(
        select(table)
        .where(func.lower(columns["ticker"]) == ticker.lower())
        .order_by(desc(columns["fiscal_date"]))
    ).mappings().all()
    if not rows:
        return {}
    # Group by statement_type, then line_item → value
    # Keep only latest fiscal_date per statement_type
    result: dict[str, dict[str, Any]] = {}
    latest_dates: dict[str, date] = {}
    for row in rows:
        st = row["statement_type"]
        fd = row["fiscal_date"]
        if st not in latest_dates or fd > latest_dates[st]:
            latest_dates[st] = fd
    for row in rows:
        st = row["statement_type"]
        fd = row["fiscal_date"]
        if fd == latest_dates.get(st):
            if st not in result:
                result[st] = {}
            result[st][row["line_item"]] = row["value"]
    return result
```

- [ ] **Step 2: Write `_fetch_stock_info()` method**

```python
def _fetch_stock_info(self, ticker: str) -> dict[str, Any] | None:
    table = self._get_table("stock_info")
    if table is None:
        return None
    columns = table.c
    row = self.db.execute(
        select(table)
        .where(func.lower(columns["ticker"]) == ticker.lower())
        .order_by(desc(columns["fetched_at"]))
        .limit(1)
    ).mappings().first()
    if row and row.get("data"):
        return row["data"]
    return None
```

- [ ] **Step 3: Write `_fetch_stock_prices()` method**

```python
def _fetch_stock_prices(self, ticker: str, limit: int = 365) -> list[dict[str, Any]]:
    table = self._get_table("stock_prices")
    if table is None:
        return []
    columns = table.c
    rows = self.db.execute(
        select(table)
        .where(func.lower(columns["ticker"]) == ticker.lower())
        .order_by(desc(columns["date"]))
        .limit(limit)
    ).mappings().all()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Write `_fetch_stock_holders()` method**

```python
def _fetch_stock_holders(self, ticker: str) -> dict[str, float]:
    table = self._get_table("stock_holders")
    if table is None:
        return {}
    columns = table.c
    rows = self.db.execute(
        select(table)
        .where(func.lower(columns["ticker"]) == ticker.lower())
        .order_by(desc(columns["date_reported"]))
    ).mappings().all()
    holder_pcts: dict[str, float] = {}
    seen: set[str] = set()
    for row in rows:
        htype = row["holder_type"]
        if htype in seen:
            continue
        seen.add(htype)
        pct = _safe_float(row.get("percent_held"))
        if pct is not None:
            holder_pcts[htype] = pct
    return holder_pcts
```

- [ ] **Step 5: Write `_fetch_nexus_options()` and `_compute_fno_metrics()` methods**

```python
def _fetch_nexus_options(self, symbol: str) -> dict[str, Any] | None:
    table = self._get_table("nexus_option_snapshots")
    if table is None:
        return None
    columns = table.c
    row = self.db.execute(
        select(table)
        .where(func.lower(columns["underlying_symbol"]) == symbol.lower())
        .order_by(desc(columns["snapshot_timestamp"]))
        .limit(1)
    ).mappings().first()
    if row:
        return dict(row)
    return None

def _compute_fno_metrics(self, nexus_row: dict[str, Any] | None) -> dict[str, Any]:
    """Compute PCR OI, ATM IV, top OI strikes from strike_details JSON array."""
    if not nexus_row:
        return {}
    strike_details = nexus_row.get("strike_details") or []
    if not strike_details:
        return {}
    spot_price = _safe_float(nexus_row.get("spot_price"))
    total_call_oi = 0
    total_put_oi = 0
    call_strikes: list[dict] = []
    put_strikes: list[dict] = []
    for sd in strike_details:
        oi = sd.get("oi", 0) or 0
        if sd.get("option_type") == "CE":
            total_call_oi += oi
            call_strikes.append(sd)
        else:
            total_put_oi += oi
            put_strikes.append(sd)
    pcr_oi = round(total_put_oi / total_call_oi, 4) if total_call_oi > 0 else None
    # Top OI strikes
    call_strikes.sort(key=lambda x: x.get("oi", 0) or 0, reverse=True)
    put_strikes.sort(key=lambda x: x.get("oi", 0) or 0, reverse=True)
    # ATM IV: find strike closest to spot
    atm_iv = None
    if spot_price and strike_details:
        closest = min(strike_details, key=lambda x: abs((x.get("strike") or 0) - spot_price))
        atm_iv = closest.get("iv")
    return {
        "pcr_oi": pcr_oi,
        "atm_iv": atm_iv,
        "net_gamma": _safe_float(nexus_row.get("net_gamma")),
        "total_gamma": _safe_float(nexus_row.get("total_gamma")),
        "gamma_flip_points": nexus_row.get("gamma_flip_points", []),
        "spot_price": spot_price,
        "expiry": str(nexus_row.get("expiry", "")),
        "strike_count": nexus_row.get("strike_count", 0),
        "top_call_oi": [
            {"strike": s["strike"], "oi": s.get("oi"), "iv": s.get("iv"), "gamma": s.get("gamma")}
            for s in call_strikes[:5]
        ],
        "top_put_oi": [
            {"strike": s["strike"], "oi": s.get("oi"), "iv": s.get("iv"), "gamma": s.get("gamma")}
            for s in put_strikes[:5]
        ],
    }
```

- [ ] **Step 6: Write `_fetch_stock_analysis()` method**

```python
def _fetch_stock_analysis(self, ticker: str) -> dict[str, Any] | None:
    table = self._get_table("stock_analysis")
    if table is None:
        return None
    columns = table.c
    row = self.db.execute(
        select(table)
        .where(func.lower(columns["ticker"]) == ticker.lower())
        .order_by(desc(columns["generated_at"]))
        .limit(1)
    ).mappings().first()
    if row and row.get("summary"):
        summary = row["summary"]
        if isinstance(summary, dict):
            return {
                "bull_case": summary.get("bull_case", []),
                "bear_case": summary.get("bear_case", []),
                "red_flags": summary.get("red_flags", []),
                "investment_thesis": summary.get("investment_thesis"),
                "confidence_score": summary.get("confidence_score"),
            }
    return None
```

---

### Task 4: Rewrite `compare_stocks()` method — core builder

**Files:**
- Modify: `app/services/stock_compare_service.py`

- [ ] **Step 1: Write `_build_core()` method**

This is the main method that assembles the `CoreComparison`:

```python
def _build_core(self, stock1: StockIdentity, stock2: StockIdentity) -> CoreComparison:
    ticker1 = getattr(stock1, 'exchange_ticker', None) or (stock1.symbol and f"{stock1.symbol}.NS")
    ticker2 = getattr(stock2, 'exchange_ticker', None) or (stock2.symbol and f"{stock2.symbol}.NS")

    # Fetch all data in parallel (sequential DB calls but minimal)
    f1 = self._fetch_financials_eav(ticker1) if ticker1 else {}
    f2 = self._fetch_financials_eav(ticker2) if ticker2 else {}
    info1 = self._fetch_stock_info(ticker1) if ticker1 else None
    info2 = self._fetch_stock_info(ticker2) if ticker2 else None
    prices1 = self._fetch_stock_prices(ticker1) if ticker1 else []
    prices2 = self._fetch_stock_prices(ticker2) if ticker2 else []
    holders1 = self._fetch_stock_holders(ticker1) if ticker1 else {}
    holders2 = self._fetch_stock_holders(ticker2) if ticker2 else {}
    nexus1 = self._fetch_nexus_options(stock1.symbol) if stock1.is_fno else None
    nexus2 = self._fetch_nexus_options(stock2.symbol) if stock2.is_fno else None
    analysis1 = self._fetch_stock_analysis(ticker1) if ticker1 else None
    analysis2 = self._fetch_stock_analysis(ticker2) if ticker2 else None

    # Helper: extract key financials from EAV
    def pivot_financials(fin: dict, stmt_type: str, fields: list[str]) -> dict:
        stmt = fin.get(stmt_type, {})
        return {field: stmt.get(field) for field in fields}

    # Identity
    identity = self._identity_section(stock1, stock2)

    # Price performance
    perf = self._build_price_performance(prices1, prices2, stock1, stock2)

    # Financials from income_statement
    fin1_inc = pivot_financials(f1, "income_statement",
        ["Total Revenue", "Operating Revenue", "Net Income", "Net Income Common Stockholders",
         "Basic EPS", "Diluted EPS", "Interest Income", "Interest Expense", "Net Interest Income",
         "Operating Expense", "Pretax Income"])
    fin2_inc = pivot_financials(f2, "income_statement", list(fin1_inc.keys()))

    # Cash flow from cashflow
    cf1 = pivot_financials(f1, "cashflow",
        ["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure",
         "Cash Dividends Paid", "Financing Cash Flow", "Investing Cash Flow",
         "Beginning Cash Position", "End Cash Position", "Changes In Cash"])
    cf2 = pivot_financials(f2, "cashflow", list(cf1.keys()))

    # Valuation/profitability/growth from stock_info JSON
    val1 = self._extract_valuation(info1)
    val2 = self._extract_valuation(info2)
    prof1 = self._extract_profitability(info1)
    prof2 = self._extract_profitability(info2)
    grow1 = self._extract_growth(info1)
    grow2 = self._extract_growth(info2)

    # FNO
    fno1 = self._compute_fno_metrics(nexus1)
    fno2 = self._compute_fno_metrics(nexus2)

    return CoreComparison(
        identity=identity,
        price_performance=perf,
        financials={"stock1": fin1_inc, "stock2": fin2_inc},
        cash_flow={"stock1": cf1, "stock2": cf2},
        valuation={"stock1": val1, "stock2": val2, "comparison": self._compare_dicts(val1, val2)},
        profitability={"stock1": prof1, "stock2": prof2, "comparison": self._compare_dicts(prof1, prof2)},
        growth={"stock1": grow1, "stock2": grow2, "comparison": self._compare_dicts(grow1, grow2)},
        holders={"stock1": holders1, "stock2": holders2},
        fno={"stock1": fno1 if stock1.is_fno else {"is_fno": False}, "stock2": fno2 if stock2.is_fno else {"is_fno": False}},
        analysis={"stock1": analysis1, "stock2": analysis2} if analysis1 or analysis2 else None,
        summary=self._build_summary(stock1, stock2, identity),
    )
```

- [ ] **Step 2: Add helper methods**

```python
def _extract_valuation(self, info: dict | None) -> dict[str, Any]:
    if not info:
        return {}
    return {
        "pe": _safe_float(info.get("trailingPE")),
        "forward_pe": _safe_float(info.get("forwardPE")),
        "pb": _safe_float(info.get("priceToBook")),
        "ev_to_revenue": _safe_float(info.get("enterpriseToRevenue")),
        "peg_ratio": _safe_float(info.get("pegRatio")),
        "market_cap": _safe_float(info.get("marketCap")),
        "enterprise_value": _safe_float(info.get("enterpriseValue")),
    }

def _extract_profitability(self, info: dict | None) -> dict[str, Any]:
    if not info:
        return {}
    return {
        "roe": _safe_float(info.get("returnOnEquity")),
        "roa": _safe_float(info.get("returnOnAssets")),
        "net_margin": _safe_float(info.get("profitMargins")),
        "operating_margin": _safe_float(info.get("operatingMargins")),
        "gross_margin": _safe_float(info.get("grossMargins")),
    }

def _extract_growth(self, info: dict | None) -> dict[str, Any]:
    if not info:
        return {}
    return {
        "revenue_growth": _safe_float(info.get("revenueGrowth")),
        "earnings_growth": _safe_float(info.get("earningsGrowth")),
        "eps": _safe_float(info.get("trailingEps")),
        "forward_eps": _safe_float(info.get("forwardEps")),
        "dividend_yield": _safe_float(info.get("dividendYield")),
        "dividend_rate": _safe_float(info.get("dividendRate")),
    }

def _compare_dicts(self, d1: dict, d2: dict) -> list[dict]:
    """Compare two dicts field-by-field, show which has higher value."""
    results = []
    all_keys = set(d1.keys()) | set(d2.keys())
    for key in all_keys:
        v1 = d1.get(key)
        v2 = d2.get(key)
        pos = self._relative_position(v1, v2)
        results.append({
            "metric": key,
            "stock1": v1,
            "stock2": v2,
            "relative_position": pos,
        })
    return results

def _build_price_performance(self, prices1: list[dict], prices2: list[dict],
                              stock1: StockIdentity, stock2: StockIdentity) -> dict[str, Any]:
    def calc_returns(prices: list[dict]) -> dict[str, Any]:
        if len(prices) < 2:
            return {}
        prices_sorted = sorted(prices, key=lambda x: x.get("date", ""))
        latest = prices_sorted[-1]
        latest_close = _safe_float(latest.get("close"))
        if latest_close is None:
            return {}
        closes = [_safe_float(p.get("close")) for p in prices_sorted]
        closes = [c for c in closes if c is not None]
        if not closes:
            return {}
        # Returns for various periods
        def pct_ret(idx):
            if idx < 0 or idx >= len(closes):
                return None
            base = closes[-(idx+1)]
            if base and base != 0:
                return round(((closes[-1] - base) / base) * 100, 2)
            return None
        high_52w = max(closes)
        low_52w = min(closes)
        return {
            "latest_close": latest_close,
            "latest_date": str(latest.get("date", "")),
            "return_1d": pct_ret(1) if len(closes) >= 2 else None,
            "return_1w": pct_ret(5) if len(closes) >= 6 else None,
            "return_1m": pct_ret(21) if len(closes) >= 22 else None,
            "return_3m": pct_ret(63) if len(closes) >= 64 else None,
            "return_6m": pct_ret(126) if len(closes) >= 127 else None,
            "return_1y": pct_ret(252) if len(closes) >= 253 else None,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "volume": _safe_int(latest.get("volume")),
        }
    return {
        stock1.slug: calc_returns(prices1),
        stock2.slug: calc_returns(prices2),
    }

def _build_summary(self, stock1: StockIdentity, stock2: StockIdentity, identity: dict) -> dict[str, Any]:
    same_sector = identity.get("same_sector", False)
    same_industry = identity.get("same_industry", False)
    if same_industry:
        summary = f"{stock1.company_name} and {stock2.company_name} are in the same industry — direct peer comparison."
        ctype = "direct_peer"
    elif same_sector:
        summary = f"{stock1.company_name} and {stock2.company_name} share the {stock1.sector} sector."
        ctype = "same_sector"
    else:
        summary = f"{stock1.company_name} and {stock2.company_name} operate in different sectors."
        ctype = "cross_sector"
    return {"summary": summary, "comparison_type": ctype}
```

---

### Task 5: Wire compare_stocks() with caching

- [ ] **Step 1: Rewrite `compare_stocks()` method**

```python
def compare_stocks(self, stock1_input: str, stock2_input: str) -> StockComparisonResponse | ComparisonErrorResponse:
    logger.info("compare_stocks: %s vs %s", stock1_input, stock2_input)
    stock1, s1_suggestions, s1_error = self.resolver.resolve_stock(stock1_input)
    stock2, s2_suggestions, s2_error = self.resolver.resolve_stock(stock2_input)

    request = ComparisonRequest(stock1_input=stock1_input, stock2_input=stock2_input)

    if stock1 is None or stock2 is None:
        errors = []
        if stock1 is None:
            errors.append(ComparisonErrorItem(side="stock1", input=stock1_input, reason=s1_error or "Stock could not be resolved"))
        if stock2 is None:
            errors.append(ComparisonErrorItem(side="stock2", input=stock2_input, reason=s2_error or "Stock could not be resolved"))
        return ComparisonErrorResponse(resolved=False, request=request, errors=errors, suggestions={"stock1": s1_suggestions, "stock2": s2_suggestions})

    if stock1.entity_id is not None and stock2.entity_id is not None and stock1.entity_id == stock2.entity_id:
        return ComparisonErrorResponse(resolved=False, request=request, errors=[ComparisonErrorItem(side="stock1", input=stock1_input, reason="Both resolve to same stock")])

    cache_slug = f"{stock1.slug}-vs-{stock2.slug}"
    cached = self._get_cached_comparison(cache_slug)
    if cached is not None:
        return cached

    # Add exchange_ticker to StockIdentity for finance table lookups
    if stock1.symbol and not getattr(stock1, 'exchange_ticker', None):
        pass  # We'll handle this via the resolver

    core = self._build_core(stock1, stock2)
    detail = self._build_detail(stock1, stock2)
    canonical_path = f"/compare/{cache_slug}"

    response = StockComparisonResponse(
        resolved=True,
        request=request,
        canonical={"comparison_slug": cache_slug, "canonical_path": canonical_path},
        stock1=stock1,
        stock2=stock2,
        core=core,
        detail=detail,
        seo=self._seo_payload(stock1, stock2, canonical_path, ...),
        data_quality=self._compute_data_quality(core, detail),
        seo_eligibility=SeoEligibility(indexable=True, ...),
        related_links=self._related_links(stock1, stock2),
    )
    self._save_cached_comparison(cache_slug, stock1, stock2, response)
    return response
```

- [ ] **Step 2: Update `_get_cached_comparison()` and `_save_cached_comparison()`**

These already work with JSONB. Update them to handle the new response type. The existing logic is fine — just ensure they use `response.model_dump(mode="json")` and `StockComparisonResponse.model_validate(payload)`.

---

### Task 6: Build detail section

- [ ] **Step 1: Write `_build_detail()` method**

```python
def _build_detail(self, stock1: StockIdentity, stock2: StockIdentity) -> DetailComparison | None:
    ticker1 = f"{stock1.symbol}.NS" if stock1.symbol else None
    ticker2 = f"{stock2.symbol}.NS" if stock2.symbol else None

    # Balance sheet from financials EAV
    f1 = self._fetch_financials_eav(ticker1) if ticker1 else {}
    f2 = self._fetch_financials_eav(ticker2) if ticker2 else {}

    bs1 = f1.get("balance_sheet", {})
    bs2 = f2.get("balance_sheet", {})
    balance_sheet = {
        "stock1": {k: bs1.get(k) for k in ["Total Assets", "Total Debt", "Cash And Cash Equivalents", "Total Equity Gross Minority Interest", "Total Liabilities Net Minority Interest", "Common Stock Equity", "Tangible Book Value", "Goodwill And Other Intangible Assets"]},
        "stock2": {k: bs2.get(k) for k in ["Total Assets", "Total Debt", "Cash And Cash Equivalents", "Total Equity Gross Minority Interest", "Total Liabilities Net Minority Interest", "Common Stock Equity", "Tangible Book Value", "Goodwill And Other Intangible Assets"]},
    }

    # Insider transactions
    ins1 = self._fetch_insider(ticker1) if ticker1 else []
    ins2 = self._fetch_insider(ticker2) if ticker2 else []

    # Earnings dates
    earn1 = self._fetch_earnings(ticker1) if ticker1 else []
    earn2 = self._fetch_earnings(ticker2) if ticker2 else []

    # Options detail (full strike_details)
    nexus1 = self._fetch_nexus_options(stock1.symbol) if stock1.is_fno else None
    nexus2 = self._fetch_nexus_options(stock2.symbol) if stock2.is_fno else None

    # Entity graph
    graph = self._build_entity_graph(stock1, stock2)

    # News
    news = self._event_news_section(stock1, stock2)

    # FII/DII
    fii_dii = self._fetch_fii_dii()

    return DetailComparison(
        balance_sheet=balance_sheet,
        insider_activity={"stock1": ins1, "stock2": ins2},
        earnings={"stock1": earn1, "stock2": earn2},
        options_detail={
            "stock1": {"strike_details": (nexus1 or {}).get("strike_details", [])[:20]} if nexus1 else {},
            "stock2": {"strike_details": (nexus2 or {}).get("strike_details", [])[:20]} if nexus2 else {},
        },
        entity_graph=graph,
        fii_dii_activity=fii_dii,
        news=news,
    )
```

- [ ] **Step 2: Add `_fetch_insider()`, `_fetch_earnings()`, `_fetch_fii_dii()`**

```python
def _fetch_insider(self, ticker: str) -> list[dict]:
    table = self._get_table("stock_insider_transactions")
    if table is None:
        return []
    columns = table.c
    rows = self.db.execute(
        select(table).where(func.lower(columns["ticker"]) == ticker.lower())
        .order_by(desc(columns["transaction_date"]))
        .limit(10)
    ).mappings().all()
    return [{"date": str(r.get("transaction_date", "")), "insider": r.get("insider_name"), "type": r.get("transaction_type"), "shares": _safe_int(r.get("shares")), "price": _safe_float(r.get("price"))} for r in rows]

def _fetch_earnings(self, ticker: str) -> list[dict]:
    table = self._get_table("stock_earnings_dates")
    if table is None:
        return []
    columns = table.c
    rows = self.db.execute(
        select(table).where(func.lower(columns["ticker"]) == ticker.lower())
        .order_by(desc(columns["report_date"]))
        .limit(4)
    ).mappings().all()
    return [{"report_date": str(r.get("report_date", "")), "eps_estimate": _safe_float(r.get("eps_estimate")), "eps_actual": _safe_float(r.get("eps_actual")), "surprise_pct": _safe_float(r.get("surprise_pct"))} for r in rows]

def _fetch_fii_dii(self) -> dict[str, Any]:
    fii_table = self._get_table("fii_activity")
    dii_table = self._get_table("dii_activity")
    result = {}
    for name, table in [("fii", fii_table), ("dii", dii_table)]:
        if table is None:
            continue
        cols = table.c
        row = self.db.execute(select(table).order_by(desc(cols["trade_date"])).limit(1)).mappings().first()
        if row:
            result[name] = dict(row)
    return result
```

---

### Task 7: Clean up unused methods and sections

- [ ] **Step 1: Remove old 25+ section methods**

Remove the following methods from StockCompareService:
- `_identity_section` → simplified version kept
- `_business_profile_section` → remove
- `_sector_industry_section` → inline in identity
- `_market_cap_section` → inline in identity
- `_price_performance_section` → replaced by `_build_price_performance`
- `_volatility_section` → remove (noise)
- `_financial_snapshot_section` → replaced by EAV pivot
- `_key_ratios_section` → removed (data from stock_info)
- `_profitability_section` → removed (data from stock_info)
- `_growth_section` → removed (data from stock_info)
- `_valuation_section` → removed (data from stock_info)
- `_balance_sheet_section` → moved to detail
- `_cash_flow_section` → replaced by EAV pivot
- `_ownership_section` → replaced by stock_holders
- `_insider_section` → moved to detail
- `_institutional_context_section` → remove
- `_event_news_section` → kept in detail
- `_entity_graph_section` → kept in detail
- `_options_section` → replaced by nexus_option_snapshots
- `_nexus_section` → remove
- `_scanner_section` → remove
- `_peer_context_section` → remove
- `_risk_factor_section` → remove
- `_data_availability_section` → simplified
- `_final_context` → remove (inline in summary)

Keep only: `_identity_section`, `_entity_graph_section`, `_event_news_section`, cache methods, and helpers.

---

### Task 8: Update API endpoint

**Files:**
- Modify: `app/api/comparison.py`

- [ ] **Step 1: Verify endpoint works with new response model**

The existing endpoint should work unchanged since the new response still uses `StockComparisonResponse`. Verify no schema changes needed.

```python
# Current code — should work as-is:
@router.get("/stocks", response_model=StockComparisonResponse | ComparisonErrorResponse)
def compare_stocks_query(stock1, stock2, db): ...
```

---

### Task 9: Test the endpoint

- [ ] **Step 1: Start the server and test**

```bash
cd /Users/madhusha/companies/arinedge/dev/portal/backend
source .venv/bin/activate
uvicorn app.main:app --port 8000 &
sleep 3
curl -s "http://localhost:8000/api/compare/stocks?stock1=sbin&stock2=icicibank" | python3 -m json.tool | head -200
```

- [ ] **Step 2: Verify the JSON structure matches spec**

Check that:
- `core.identity` exists with stock details
- `core.financials` has stock1/stock2 with Total Revenue, Net Income, EPS
- `core.cash_flow` has Operating Cash Flow, Free Cash Flow
- `core.valuation` has PE, PB
- `core.fno` has pcr_oi, net_gamma, top_call_oi
- `core.holders` has holder_type percentages
- `data_quality.completeness_score` is reasonable
