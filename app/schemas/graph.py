from datetime import datetime, date
from pydantic import BaseModel


class CanonicalEntityOut(BaseModel):
    id: int
    canonical_name: str
    entity_type: str
    sector: str | None = None
    ticker: str | None = None
    isin: str | None = None
    description: str | None = None
    confidence: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class EntityAliasOut(BaseModel):
    id: int
    canonical_id: int
    alias: str
    alias_type: str
    confidence: float | None = None
    source: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None

    model_config = {"from_attributes": True}


class GraphEventOut(BaseModel):
    id: int
    extraction_id: int
    news_id: int
    event_type_raw: str | None = None
    sentiment: str | None = None
    confidence: float | None = None
    importance: int | None = None
    evidence_span: str | None = None
    event_date: date | None = None
    article_date: datetime | None = None
    meta_data: dict | None = None

    model_config = {"from_attributes": True}


class RelationshipOut(BaseModel):
    id: int
    source_entity: int
    target_entity: int
    relation_type: str
    weight: float
    confidence: float
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    source_count: int
    meta_data: dict | None = None

    model_config = {"from_attributes": True}


class GraphMetricOut(BaseModel):
    entity_id: int
    pagerank: float | None = None
    degree_centrality: float | None = None
    betweenness: float | None = None
    mention_velocity: float | None = None
    sentiment_score: float | None = None
    sentiment_velocity: float | None = None
    cluster_id: int | None = None
    computed_at: datetime | None = None

    model_config = {"from_attributes": True}


class PropagationScoreOut(BaseModel):
    id: int
    source_id: int
    target_id: int
    propagation_score: float | None = None
    influence_path: list[str] | None = None
    hop_count: int | None = None
    decay_factor: float | None = None
    computed_at: datetime | None = None

    model_config = {"from_attributes": True}


class CanonicalEntityDetail(CanonicalEntityOut):
    aliases: list[EntityAliasOut]
    metrics: GraphMetricOut | None = None


class EntityResolutionLogOut(BaseModel):
    id: int
    extraction_id: int
    raw_name: str
    resolved_id: int
    confidence: float | None = None
    method: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class EntityMergeRequest(BaseModel):
    source_ids: list[int]
    target_id: int
    merge_metadata: dict | None = None


class RelationshipOverrideRequest(BaseModel):
    relationship_id: int
    relation_type: str | None = None
    weight: float | None = None
    confidence: float | None = None


class EntitySearchParams(BaseModel):
    query: str | None = None
    entity_type: str | None = None
    sector: str | None = None
    ticker: str | None = None
    limit: int = 50
    offset: int = 0


class GraphQueryParams(BaseModel):
    entity_ids: list[int] | None = None
    relation_types: list[str] | None = None
    max_depth: int = 2
    min_weight: float = 0.0
    limit: int = 200


class GraphDataResponse(BaseModel):
    entities: list[CanonicalEntityOut]
    relationships: list[RelationshipOut]
    metrics: dict[int, GraphMetricOut] | None = None
