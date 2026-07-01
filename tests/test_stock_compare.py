from sqlalchemy import create_engine

from app.api import comparison as comparison_api
from app.schemas.compare import (
    ComparisonRequest,
    ComparisonSuggestion,
    StockComparisonResponse,
    StockIdentity,
    DataQuality,
    SeoEligibility,
)
from app.services.stock_compare_service import (
    StockCompareService,
    _normalize_input,
    _slugify,
)


class _DummySession:
    def __init__(self):
        self._engine = create_engine("sqlite:///:memory:")

    def get_bind(self):
        return self._engine


def _stock(symbol: str, slug: str, company_name: str, entity_id: int = 1) -> StockIdentity:
    return StockIdentity(
        symbol=symbol,
        exchange_symbol=f"{symbol}.NS",
        slug=slug,
        company_name=company_name,
        short_name=company_name,
        isin=None,
        sector="Test Sector",
        industry="Test Industry",
        market_cap=None,
        listing_status="listed",
        is_fno=False,
        canonical_path=f"/stocks/{slug}",
        resolved_from="symbol",
        resolution_confidence=1.0,
        entity_id=entity_id,
    )


def test_normalization_handles_common_stock_inputs():
    assert _normalize_input("HDFC-Bank") == "hdfcbank"
    assert _normalize_input("M&M") == "mandm"
    assert _slugify("Maruti Suzuki India Limited") == "maruti-suzuki-india-limited"
    assert _slugify("M&M") == "m-and-m"


def test_compare_stocks_returns_noindex_when_unresolved():
    service = StockCompareService(_DummySession())

    def resolve_side(value: str):
        if value == "maruti":
            return _stock("MARUTI", "maruti", "Maruti Suzuki India Limited"), [], None
        return None, [
            ComparisonSuggestion(
                symbol="INDIAMART",
                company_name="Indiamart Intermesh Limited",
                slug="indiamart",
                canonical_path="/stocks/indiamart",
            )
        ], "Stock could not be resolved"

    service.resolver.resolve_stock = resolve_side  # type: ignore[method-assign]

    result = service.compare_stocks("maruti", "missing")

    assert result.resolved is False
    assert result.seo_eligibility.noindex_recommended is True
    assert result.errors[0].side == "stock2"


def test_compare_stocks_detects_same_stock():
    service = StockCompareService(_DummySession())
    stock = _stock("MARUTI", "maruti", "Maruti Suzuki India Limited", entity_id=101)

    def resolve_side(_: str):
        return stock, [], None

    service.resolver.resolve_stock = resolve_side  # type: ignore[method-assign]

    result = service.compare_stocks("maruti", "maruti")

    assert result.resolved is False
    assert result.seo_eligibility.noindex_recommended is True
    assert "same stock" in result.errors[0].reason.lower()


def test_compare_stocks_success_path_uses_canonical_slug_and_seo():
    service = StockCompareService(_DummySession())
    left = _stock("MARUTI", "maruti", "Maruti Suzuki India Limited", entity_id=101)
    right = _stock("INDIAMART", "indiamart", "Indiamart Intermesh Limited", entity_id=102)

    def resolve_side(value: str):
        if value == "maruti":
            return left, [], None
        return right, [], None

    service.resolver.resolve_stock = resolve_side  # type: ignore[method-assign]
    service._identity_section = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "same_sector": False,
        "same_industry": False,
        "comparison_type": "cross_sector",
    }
    service._business_profile_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._sector_industry_section = lambda *args, **kwargs: {"status": "available"}  # type: ignore[method-assign]
    service._market_cap_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._price_performance_section = lambda *args, **kwargs: {"status": "available", "latest_date": "2026-06-16"}  # type: ignore[method-assign]
    service._volatility_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._financial_snapshot_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._key_ratios_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._profitability_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._growth_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._valuation_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._balance_sheet_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._cash_flow_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._ownership_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._insider_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._institutional_context_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._event_news_section = lambda *args, **kwargs: {"status": "available", "stock1": {"latest_items": [{"published_at": "2026-06-16T00:00:00+00:00"}]}, "stock2": {"latest_items": []}}  # type: ignore[method-assign]
    service._entity_graph_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._options_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._nexus_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._scanner_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._peer_context_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._risk_section = lambda *args, **kwargs: {"status": "missing"}  # type: ignore[method-assign]
    service._data_availability_section = lambda sections: DataQuality(
        status="partial",
        completeness_score=50,
        available_sections=["identity_comparison", "price_performance_comparison"],
        missing_sections=[],
        stale_sections=[],
        last_updated="2026-06-16T00:00:00+00:00",
        warnings=[],
    )
    service._final_context = lambda *args, **kwargs: {"summary": "ok"}  # type: ignore[method-assign]
    service._seo_payload = lambda *args, **kwargs: {"title": "t", "description": "d", "h1": "h", "canonical_path": "/compare/maruti-vs-indiamart", "breadcrumbs": []}  # type: ignore[method-assign]
    service._seo_eligibility = lambda *args, **kwargs: SeoEligibility(
        indexable=True,
        sitemap_eligible=True,
        noindex_recommended=False,
        reason="ok",
        minimum_content_passed=True,
    )
    service._related_links = lambda *args, **kwargs: []  # type: ignore[method-assign]

    result = service.compare_stocks("maruti", "indiamart")

    assert result.resolved is True
    assert result.canonical["comparison_slug"] == "maruti-vs-indiamart"
    assert result.canonical["canonical_path"] == "/compare/maruti-vs-indiamart"
    assert result.seo_eligibility.indexable is True
    assert result.seo_eligibility.noindex_recommended is False


def test_compare_stocks_returns_cached_response_when_fresh():
    service = StockCompareService(_DummySession())
    cached = StockComparisonResponse(
        resolved=True,
        request=ComparisonRequest(stock1_input="maruti", stock2_input="indiamart"),
        canonical={"comparison_slug": "maruti-vs-indiamart", "canonical_path": "/compare/maruti-vs-indiamart"},
        stock1=_stock("MARUTI", "maruti", "Maruti Suzuki India Limited", entity_id=101),
        stock2=_stock("INDIAMART", "indiamart", "Indiamart Intermesh Limited", entity_id=102),
        seo={"title": "cached"},
        summary={"summary": "cached"},
        sections={"identity_comparison": {"status": "available"}},
        tables={},
        charts={},
        related_links=[],
        data_quality=DataQuality(status="partial", completeness_score=50, available_sections=["identity_comparison"], missing_sections=[], stale_sections=[], last_updated=None, warnings=[]),
        seo_eligibility=SeoEligibility(indexable=True, sitemap_eligible=True, noindex_recommended=False, reason="cached", minimum_content_passed=True),
    )

    service.resolver.resolve_stock = lambda value: (_stock("MARUTI", "maruti", "Maruti Suzuki India Limited", entity_id=101), [], None) if value == "maruti" else (_stock("INDIAMART", "indiamart", "Indiamart Intermesh Limited", entity_id=102), [], None)  # type: ignore[method-assign]
    service._get_cached_comparison = lambda slug: cached if slug == "maruti-vs-indiamart" else None  # type: ignore[method-assign]
    service._save_cached_comparison = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("cache save should not run"))  # type: ignore[method-assign]
    service._identity_section = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not recompute"))  # type: ignore[method-assign]

    result = service.compare_stocks("maruti", "indiamart")

    assert result.seo["title"] == "cached"
    assert result.canonical["comparison_slug"] == "maruti-vs-indiamart"


def test_route_functions_delegate_to_comparison_service(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeService:
        def __init__(self, db):
            self.db = db

        def compare_stocks(self, stock1: str, stock2: str):
            calls.append((stock1, stock2))
            return {"resolved": True}

    monkeypatch.setattr(comparison_api, "StockCompareService", FakeService)

    response_1 = comparison_api.compare_stocks_query(stock1="maruti", stock2="indiamart", db=None)
    response_2 = comparison_api.compare_stocks_path(stock1="hdfcbank", stock2="icicibank", db=None)

    assert response_1 == {"resolved": True}
    assert response_2 == {"resolved": True}
    assert calls == [("maruti", "indiamart"), ("hdfcbank", "icicibank")]


def test_compare_route_returns_structured_error_on_unhandled_failure(monkeypatch):
    class FailingService:
        def __init__(self, db):
            self.db = db

        def compare_stocks(self, stock1: str, stock2: str):
            raise RuntimeError("boom")

    monkeypatch.setattr(comparison_api, "StockCompareService", FailingService)

    response = comparison_api.compare_stocks_query(stock1="BEL", stock2="HAL", db=None)

    assert response.resolved is False
    assert response.seo_eligibility.noindex_recommended is True
    assert response.request.stock1_input == "BEL"
    assert response.request.stock2_input == "HAL"


def test_fno_metrics_tolerates_malformed_strike_details():
    service = StockCompareService(_DummySession())

    result = service._compute_fno_metrics(
        {
            "spot_price": 100,
            "expiry": "2026-06-25",
            "strike_details": [
                {"option_type": "CE", "strike": 100, "oi": "1200", "volume": "25", "iv": "14.5"},
                {"option_type": "PE", "oi": None, "volume": None},
                "bad-row",
                {"option_type": "PE", "strike": "95", "oi": "900", "volume": "20", "iv": "15.1"},
            ],
        }
    )

    assert result["is_fno"] is True
    assert result["pcr_oi"] == 0.75
    assert result["top_call_oi"][0]["strike"] == 100
    assert result["top_put_oi"][0]["strike"] == 95
