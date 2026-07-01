from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.compare import DataQuality, RelatedLink, SeoEligibility, StockIdentity


class LandingSectionStatus(BaseModel):
    status: Literal["available", "partial", "missing"] = "missing"
    summary: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class LandingEntity(BaseModel):
    stock: StockIdentity | None = None
    sector: dict[str, Any] | None = None


class LandingResponse(BaseModel):
    canonical_path: str
    entity: LandingEntity = Field(default_factory=LandingEntity)
    sections: dict[str, LandingSectionStatus] = Field(default_factory=dict)
    related_links: list[RelatedLink] = Field(default_factory=list)
    faq: list[dict[str, str]] = Field(default_factory=list)
    schema_payload: dict[str, Any] = Field(default_factory=dict)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    seo_eligibility: SeoEligibility = Field(default_factory=SeoEligibility)

