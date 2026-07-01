from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ComparisonValue(BaseModel):
    raw_value: Any | None = None
    display_value: str | None = None
    unit: str | None = None
    period: str | None = None
    date: str | None = None
    source_table: str | None = None
    availability: str | None = None


class ComparisonMetric(BaseModel):
    metric: str
    stock1: ComparisonValue = Field(default_factory=ComparisonValue)
    stock2: ComparisonValue = Field(default_factory=ComparisonValue)
    relative_position: Literal[
        "stock1_higher",
        "stock2_higher",
        "similar",
        "not_available",
    ] = "not_available"
    interpretation: str | None = None


class StockIdentity(BaseModel):
    symbol: str | None = None
    exchange_symbol: str | None = None
    slug: str
    company_name: str
    short_name: str | None = None
    description: str | None = None
    isin: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    listing_status: Literal["listed", "delisted", "unknown"] = "unknown"
    is_fno: bool = False
    canonical_path: str
    resolved_from: Literal[
        "symbol",
        "slug",
        "alias",
        "company_name",
        "fuzzy",
        "ticker",
        "nse_security",
        "market_data",
    ] = "fuzzy"
    resolution_confidence: float = 0.0
    entity_id: int | None = None
    source_tables: list[str] = Field(default_factory=list)


class RelatedLink(BaseModel):
    label: str
    path: str
    enabled: bool = True


class DataQuality(BaseModel):
    status: Literal["complete", "partial", "limited", "missing"] = "missing"
    completeness_score: int = 0
    available_sections: list[str] = Field(default_factory=list)
    missing_sections: list[str] = Field(default_factory=list)
    stale_sections: list[str] = Field(default_factory=list)
    last_updated: str | None = None
    warnings: list[str] = Field(default_factory=list)


class SeoEligibility(BaseModel):
    indexable: bool = False
    sitemap_eligible: bool = False
    noindex_recommended: bool = True
    reason: str = "Insufficient data"
    minimum_content_passed: bool = False


class ComparisonErrorItem(BaseModel):
    side: Literal["stock1", "stock2"]
    input: str
    reason: str


class ComparisonSuggestion(BaseModel):
    symbol: str | None = None
    company_name: str
    slug: str
    canonical_path: str
    exchange_symbol: str | None = None
    isin: str | None = None
    sector: str | None = None
    industry: str | None = None
    listing_status: Literal["listed", "delisted", "unknown"] = "unknown"
    is_fno: bool = False
    resolution_confidence: float = 0.0


class ComparisonRequest(BaseModel):
    stock1_input: str
    stock2_input: str


class ComparisonSummary(BaseModel):
    summary: str
    stock1_note: str | None = None
    stock2_note: str | None = None
    comparison_type: Literal["direct_peer", "same_sector", "cross_sector", "unknown"] = "unknown"


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


class StockResolveResponse(BaseModel):
    resolved: bool
    input: str
    stock: StockIdentity | None = None
    suggestions: list[ComparisonSuggestion] = Field(default_factory=list)
    error: str | None = None


class ComparisonErrorResponse(BaseModel):
    resolved: bool = False
    request: ComparisonRequest
    errors: list[ComparisonErrorItem] = Field(default_factory=list)
    suggestions: dict[str, list[ComparisonSuggestion]] = Field(default_factory=dict)
    seo_eligibility: SeoEligibility = Field(default_factory=SeoEligibility)


class ComparisonMetricBlock(BaseModel):
    section: str
    metrics: list[ComparisonMetric] = Field(default_factory=list)


class ComparisonSection(BaseModel):
    name: str
    status: Literal["available", "partial", "missing"] = "missing"
    summary: str | None = None
    metrics: list[ComparisonMetric] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


class ComparisonTableRow(BaseModel):
    metric: str
    stock1: ComparisonValue = Field(default_factory=ComparisonValue)
    stock2: ComparisonValue = Field(default_factory=ComparisonValue)
    relative_position: Literal[
        "stock1_higher",
        "stock2_higher",
        "similar",
        "not_available",
    ] = "not_available"
    source_table: str | None = None
