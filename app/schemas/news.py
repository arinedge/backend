import json
from datetime import datetime
from pydantic import BaseModel, field_validator


class NewsArticleOut(BaseModel):
    id: int
    guid: str | None = None
    title: str | None = None
    link: str | None = None
    description: str | None = None
    author: str | None = None
    category: str | None = None
    image_url: str | None = None
    source_name: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class NewsExtractionOut(BaseModel):
    id: int
    news_id: int
    status: str | None = None
    raw_llm_response: dict | None = None
    validated_output: dict | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    provider: str | None = None
    model: str | None = None
    error_message: str | None = None
    retry_count: int | None = None
    processing_time_ms: int | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_validator("raw_llm_response", "validated_output", mode="before")
    @classmethod
    def parse_json_string(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return v
        return v


class PaginatedNewsResponse(BaseModel):
    items: list[NewsArticleOut]
    total: int
    page: int
    per_page: int
    pages: int
    has_next: bool
    has_prev: bool


class NewsFiltersOut(BaseModel):
    sources: list[str]
    authors: list[str]
    date_range: dict
