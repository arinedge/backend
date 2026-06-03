from datetime import datetime, date
from sqlalchemy import Integer, Text, String, DateTime, JSON, Float, Boolean, Date, BigInteger, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import ARRAY
from app.database import Base


class CanonicalEntity(Base):
    __tablename__ = "nse_canonical_entities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)
    ticker: Mapped[str | None] = mapped_column(Text, nullable=True)
    isin: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, server_default="1.0")
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())

    aliases = relationship("EntityAlias", back_populates="entity", cascade="all, delete-orphan")


class EntityAlias(Base):
    __tablename__ = "nse_entity_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nse_canonical_entities.id"), nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, server_default="0.8")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())

    entity = relationship("CanonicalEntity", back_populates="aliases")


class EntityEmbedding(Base):
    __tablename__ = "nse_entity_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    embedding: Mapped[list | None] = mapped_column(ARRAY(Float), nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EntityResolutionLog(Base):
    __tablename__ = "nse_entity_resolution_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_name: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventType(Base):
    __tablename__ = "nse_event_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    parent_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default="true")


class GraphEvent(Base):
    __tablename__ = "nse_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(Integer, nullable=False)
    news_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    importance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    article_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Relationship(Base):
    __tablename__ = "nse_relationships"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_entity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_entity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float | None] = mapped_column(Float, server_default="1.0")
    confidence: Mapped[float | None] = mapped_column(Float, server_default="0.5")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_count: Mapped[int | None] = mapped_column(Integer, server_default="1")
    meta_data: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


class RelationshipEvidence(Base):
    __tablename__ = "nse_relationship_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    relationship_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    extraction_id: Mapped[int] = mapped_column(Integer, nullable=False)
    news_id: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GraphMetric(Base):
    __tablename__ = "nse_graph_metrics"

    entity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pagerank: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    degree_centrality: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    betweenness: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    mention_velocity: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    sentiment_score: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    sentiment_velocity: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PropagationScore(Base):
    __tablename__ = "nse_propagation_scores"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    propagation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    influence_path: Mapped[list | None] = mapped_column(ARRAY(Text), nullable=True)
    hop_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decay_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
