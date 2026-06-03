# Event Chain Intelligence Engine — Phase 1+2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the Event Chain Intelligence Engine within the existing backend FastAPI service — entity resolution, event normalization, graph engine, propagation, analytics, and full frontend.

**Architecture:** PostgreSQL-only hybrid with pgvector embeddings, Redis cache, Cytoscape.js frontend. Incremental processing via cursor tracking. JSON repair layer for malformed LLM output.

**Tech Stack:** FastAPI (Python 3.14), SQLAlchemy 2.0, Alembic, PostgreSQL 16, Redis 7, Angular 21, Cytoscape.js

---

### Task 1: Database Migration — Create All nse_* Tables

**Files:**
- Create: `backend/alembic/versions/2026_05_21_add_event_chain_tables.py`

- [ ] **Step 1: Create the Alembic migration**

Create file `backend/alembic/versions/2026_05_21_add_event_chain_tables.py` with the following content:

```python
"""add event chain intelligence tables

Revision ID: add_event_chain_tables
Revises: (update with actual previous revision)
Create Date: 2026-05-21
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "add_event_chain_tables"
down_revision: Union[str, None] = None  # UPDATE: check current head
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    # nse_canonical_entities
    op.create_table(
        "nse_canonical_entities",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column("isin", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_name"),
    )

    # nse_entity_aliases
    op.create_table(
        "nse_entity_aliases",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("canonical_id", sa.BigInteger(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("alias_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="0.8"),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["canonical_id"], ["nse_canonical_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_aliases_alias", "nse_entity_aliases", ["alias"])
    op.execute("CREATE INDEX ix_entity_aliases_alias_trgm ON nse_entity_aliases USING gin (alias gin_trgm_ops)")

    # nse_entity_embeddings
    op.create_table(
        "nse_entity_embeddings",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("canonical_id", sa.BigInteger(), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["canonical_id"], ["nse_canonical_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # nse_entity_resolution_log
    op.create_table(
        "nse_entity_resolution_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("extraction_id", sa.Integer(), nullable=False),
        sa.Column("raw_name", sa.Text(), nullable=False),
        sa.Column("resolved_id", sa.BigInteger(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["extraction_id"], ["news_extraction.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_id"], ["nse_canonical_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # nse_event_types
    op.create_table(
        "nse_event_types",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("parent_type", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_type"),
    )

    # nse_events
    op.create_table(
        "nse_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("extraction_id", sa.Integer(), nullable=False),
        sa.Column("news_id", sa.Integer(), nullable=False),
        sa.Column("event_type_id", sa.Integer(), nullable=True),
        sa.Column("event_type_raw", sa.Text(), nullable=True),
        sa.Column("sentiment", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=True),
        sa.Column("evidence_span", sa.Text(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("article_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["extraction_id"], ["news_extraction.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["news_id"], ["market_news.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_type_id"], ["nse_event_types.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nse_events_news_id", "nse_events", ["news_id"])
    op.create_index("ix_nse_events_extraction_id", "nse_events", ["extraction_id"])

    # nse_relationships
    op.create_table(
        "nse_relationships",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_entity", sa.BigInteger(), nullable=False),
        sa.Column("target_entity", sa.BigInteger(), nullable=False),
        sa.Column("relation_type", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), server_default="1.0"),
        sa.Column("confidence", sa.Float(), server_default="0.5"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source_count", sa.Integer(), server_default="1"),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["source_entity"], ["nse_canonical_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_entity"], ["nse_canonical_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nse_relationships_src_tgt", "nse_relationships", ["source_entity", "target_entity"])

    # nse_relationship_evidence
    op.create_table(
        "nse_relationship_evidence",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("relationship_id", sa.BigInteger(), nullable=False),
        sa.Column("extraction_id", sa.Integer(), nullable=False),
        sa.Column("news_id", sa.Integer(), nullable=False),
        sa.Column("evidence_span", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["relationship_id"], ["nse_relationships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_id"], ["news_extraction.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["news_id"], ["market_news.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # nse_graph_metrics
    op.create_table(
        "nse_graph_metrics",
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("pagerank", sa.Float(), server_default="0.0"),
        sa.Column("degree_centrality", sa.Float(), server_default="0.0"),
        sa.Column("betweenness", sa.Float(), server_default="0.0"),
        sa.Column("mention_velocity", sa.Float(), server_default="0.0"),
        sa.Column("sentiment_score", sa.Float(), server_default="0.0"),
        sa.Column("sentiment_velocity", sa.Float(), server_default="0.0"),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["entity_id"], ["nse_canonical_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_id"),
    )

    # nse_propagation_scores
    op.create_table(
        "nse_propagation_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("propagation_score", sa.Float(), nullable=True),
        sa.Column("influence_path", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("hop_count", sa.Integer(), nullable=True),
        sa.Column("decay_factor", sa.Float(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_id"], ["nse_canonical_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["nse_canonical_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_propagation_src_tgt", "nse_propagation_scores", ["source_id", "target_id"])

    # Seed event types
    event_types = [
        "MOU", "PARTNERSHIP", "ACQUISITION", "MERGER", "INVESTMENT",
        "CONTRACT_AWARD", "SUPPLY_AGREEMENT", "DEFENSE_ORDER",
        "GOVERNMENT_APPROVAL", "REGULATORY_ACTION", "BOARD_CHANGE",
        "EXECUTIVE_APPOINTMENT", "EXECUTIVE_RESIGNATION",
        "REVENUE_GROWTH", "REVENUE_DECLINE", "EARNINGS",
        "DIVIDEND", "BUYBACK", "FUNDRAISING",
        "CAPACITY_EXPANSION", "PLANT_LAUNCH", "PRODUCT_LAUNCH",
        "EXPORT_DEAL", "AI_PARTNERSHIP", "SEMICONDUCTOR_EXPANSION",
        "PRICE_TARGET_CHANGE", "ANALYST_UPGRADE", "ANALYST_DOWNGRADE",
        "MACRO_EVENT", "SECTOR_TREND", "MARKET_MOVEMENT",
    ]
    for et in event_types:
        op.execute(f"INSERT INTO nse_event_types (event_type) VALUES ('{et}') ON CONFLICT DO NOTHING")

def downgrade():
    op.drop_table("nse_propagation_scores")
    op.drop_table("nse_graph_metrics")
    op.drop_table("nse_relationship_evidence")
    op.drop_table("nse_relationships")
    op.drop_table("nse_events")
    op.drop_table("nse_event_types")
    op.drop_table("nse_entity_resolution_log")
    op.drop_table("nse_entity_embeddings")
    op.drop_table("nse_entity_aliases")
    op.drop_table("nse_canonical_entities")
```

- [ ] **Step 2: Run migration**

```bash
cd backend && alembic upgrade head
```

Expected: All 10 `nse_*` tables created. Verify with `psql -d arinedge_db -c '\dt nse_*'`.

- [ ] **Step 3: Verify seed data**

```bash
cd backend && python3 -c "
from app.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    result = conn.execute(text('SELECT count(*) FROM nse_event_types'))
    print(f'Event types seeded: {result.scalar()}')
"
```

Expected: Output "Event types seeded: 31"

---

### Task 2: Backend Models — SQLAlchemy Models for Graph Tables

**Files:**
- Create: `backend/app/models/graph.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create graph models file**

Create `backend/app/models/graph.py`:

```python
from datetime import datetime
from sqlalchemy import (
    Column, BigInteger, Integer, Text, Float, Boolean, Date,
    DateTime, JSON, ForeignKey, Identity,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ARRAY
from app.database import Base


class CanonicalEntity(Base):
    __tablename__ = "nse_canonical_entities"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)
    ticker: Mapped[str | None] = mapped_column(Text, nullable=True)
    isin: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, server_default="1.0")
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")
    aliases = relationship("EntityAlias", back_populates="entity", cascade="all, delete-orphan")


class EntityAlias(Base):
    __tablename__ = "nse_entity_aliases"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    canonical_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nse_canonical_entities.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, server_default="0.8")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")
    entity = relationship("CanonicalEntity", back_populates="aliases")


class EntityEmbedding(Base):
    __tablename__ = "nse_entity_embeddings"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    canonical_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nse_canonical_entities.id", ondelete="CASCADE"), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")


class EntityResolutionLog(Base):
    __tablename__ = "nse_entity_resolution_log"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    extraction_id: Mapped[int] = mapped_column(Integer, ForeignKey("news_extraction.id", ondelete="CASCADE"), nullable=False)
    raw_name: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nse_canonical_entities.id", ondelete="CASCADE"), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")


class EventType(Base):
    __tablename__ = "nse_event_types"
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    parent_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool | None] = mapped_column(Boolean, server_default="true")


class GraphEvent(Base):
    __tablename__ = "nse_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    extraction_id: Mapped[int] = mapped_column(Integer, ForeignKey("news_extraction.id", ondelete="CASCADE"), nullable=False)
    news_id: Mapped[int] = mapped_column(Integer, ForeignKey("market_news.id", ondelete="CASCADE"), nullable=False)
    event_type_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("nse_event_types.id", ondelete="SET NULL"), nullable=True)
    event_type_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    importance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    article_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")


class Relationship(Base):
    __tablename__ = "nse_relationships"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_entity: Mapped[int] = mapped_column(BigInteger, ForeignKey("nse_canonical_entities.id", ondelete="CASCADE"), nullable=False)
    target_entity: Mapped[int] = mapped_column(BigInteger, ForeignKey("nse_canonical_entities.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[float | None] = mapped_column(Float, server_default="1.0")
    confidence: Mapped[float | None] = mapped_column(Float, server_default="0.5")
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")
    source_count: Mapped[int | None] = mapped_column(Integer, server_default="1")
    metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class RelationshipEvidence(Base):
    __tablename__ = "nse_relationship_evidence"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    relationship_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nse_relationships.id", ondelete="CASCADE"), nullable=False)
    extraction_id: Mapped[int] = mapped_column(Integer, ForeignKey("news_extraction.id", ondelete="CASCADE"), nullable=False)
    news_id: Mapped[int] = mapped_column(Integer, ForeignKey("market_news.id", ondelete="CASCADE"), nullable=False)
    evidence_span: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")


class GraphMetric(Base):
    __tablename__ = "nse_graph_metrics"
    entity_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nse_canonical_entities.id", ondelete="CASCADE"), primary_key=True)
    pagerank: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    degree_centrality: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    betweenness: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    mention_velocity: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    sentiment_score: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    sentiment_velocity: Mapped[float | None] = mapped_column(Float, server_default="0.0")
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")


class PropagationScore(Base):
    __tablename__ = "nse_propagation_scores"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nse_canonical_entities.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("nse_canonical_entities.id", ondelete="CASCADE"), nullable=False)
    propagation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    influence_path: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    hop_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decay_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default="now()")
```

- [ ] **Step 2: Update models __init__.py**

Append to `backend/app/models/__init__.py`:
```python
from app.models.graph import (
    CanonicalEntity, EntityAlias, EntityEmbedding, EntityResolutionLog,
    EventType, GraphEvent, Relationship, RelationshipEvidence,
    GraphMetric, PropagationScore,
)
```

---

### Task 3: Pydantic Schemas for Graph API

**Files:**
- Create: `backend/app/schemas/graph.py`

- [ ] **Step 1: Create all Pydantic schemas**

Create `backend/app/schemas/graph.py`:

```python
from datetime import datetime, date
from pydantic import BaseModel


class CanonicalEntityOut(BaseModel):
    id: int
    canonical_name: str
    entity_type: str
    sector: str | None = None
    ticker: str | None = None
    isin: str | None = None
    confidence: float | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    model_config = {"from_attributes": True}


class CanonicalEntityDetail(CanonicalEntityOut):
    aliases: list["EntityAliasOut"] = []
    metrics: "GraphMetricOut | None" = None


class CanonicalEntityCreate(BaseModel):
    canonical_name: str
    entity_type: str
    sector: str | None = None
    ticker: str | None = None
    isin: str | None = None
    description: str | None = None


class CanonicalEntityUpdate(BaseModel):
    canonical_name: str | None = None
    entity_type: str | None = None
    sector: str | None = None
    ticker: str | None = None
    isin: str | None = None
    description: str | None = None
    confidence: float | None = None


class EntityAliasOut(BaseModel):
    id: int
    canonical_id: int
    alias: str
    alias_type: str
    confidence: float | None = None
    source: str | None = None
    model_config = {"from_attributes": True}


class EntityAliasCreate(BaseModel):
    canonical_id: int
    alias: str
    alias_type: str = "manual"
    confidence: float = 1.0
    source: str = "manual"


class EntityAliasUpdate(BaseModel):
    alias: str | None = None
    confidence: float | None = None


class GraphEventOut(BaseModel):
    id: int
    extraction_id: int
    news_id: int
    event_type: str | None = None
    event_type_raw: str | None = None
    sentiment: str | None = None
    confidence: float | None = None
    importance: int | None = None
    evidence_span: str | None = None
    event_date: date | None = None
    article_date: datetime | None = None
    created_at: datetime | None = None
    model_config = {"from_attributes": True}


class EventTypeOut(BaseModel):
    id: int
    event_type: str
    parent_type: str | None = None
    description: str | None = None
    model_config = {"from_attributes": True}


class GraphNodeOut(BaseModel):
    id: str
    name: str
    type: str
    sector: str | None = None
    centrality: float = 0.0
    mention_count: int = 0
    distance: int = 0


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    relation_type: str
    weight: float = 1.0
    confidence: float = 0.5


class SubgraphOut(BaseModel):
    nodes: list[GraphNodeOut] = []
    edges: list[GraphEdgeOut] = []
    total_nodes: int = 0
    total_edges: int = 0


class TimelineEvent(BaseModel):
    id: int
    title: str
    timestamp: str
    event_type: str
    sentiment: str | None = None
    confidence: float | None = None
    evidence_span: str | None = None
    news_id: int
    article_link: str | None = None


class TimelineOut(BaseModel):
    entity: str
    events: list[TimelineEvent] = []
    total_events: int = 0
    date_range: dict | None = None


class GraphMetricOut(BaseModel):
    entity_id: int
    pagerank: float = 0.0
    degree_centrality: float = 0.0
    betweenness: float = 0.0
    mention_velocity: float = 0.0
    sentiment_score: float = 0.0
    sentiment_velocity: float = 0.0
    cluster_id: int | None = None
    computed_at: datetime | None = None
    model_config = {"from_attributes": True}


class StatsOut(BaseModel):
    total_entities: int = 0
    total_relationships: int = 0
    total_events: int = 0
    total_articles_processed: int = 0
    entity_types: dict = {}
    top_entities: list[dict] = []


class PropagationPath(BaseModel):
    source: str
    target: str
    score: float
    path: list[str]
    hops: int
    decay: float


class AlertOut(BaseModel):
    id: int
    entity_id: int
    entity_name: str
    event_type: str | None = None
    threshold: float | None = None
    is_active: bool = True
    created_at: datetime | None = None


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
    pages: int
    has_next: bool
    has_prev: bool
```

---

### Task 4: JSON Repair Layer

**Files:**
- Create: `backend/app/components/__init__.py`
- Create: `backend/app/components/graph/__init__.py`
- Create: `backend/app/components/graph/json_repair.py`

- [ ] **Step 1: Create `__init__.py` files**

```bash
touch backend/app/components/__init__.py backend/app/components/graph/__init__.py
```

- [ ] **Step 2: Create `json_repair.py`**

Create `backend/app/components/graph/json_repair.py`:

```python
import json
import re
import logging

logger = logging.getLogger(__name__)


def parse_llm_raw(raw_value) -> dict | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        return _parse_string(raw_value)
    return None


def _parse_string(raw: str) -> dict | None:
    s = raw.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    s = s.replace("\\n", "\n").replace("\\t", "\t")
    try:
        inner = json.loads(s)
        if isinstance(inner, dict):
            return inner
        if isinstance(inner, str):
            return _parse_string(inner)
        return None
    except json.JSONDecodeError:
        pass
    return _repair_json(s)


def _repair_json(s: str) -> dict | None:
    repairs = []
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*]", "]", s)
    s = re.sub(r"(?<!\\)'", '"', s)
    s = re.sub(r"(?<!\\)\\(?!/[\\\"bfnrtu])", "", s)
    s = re.sub(r":\s*'([^']*?)'", r': "\1"', s)
    try:
        result = json.loads(s)
        logger.debug(f"JSON repaired for pattern: {repairs}")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"JSON repair failed: {e}")
        return None
```

---

### Task 5: Entity Resolver Component

**Files:**
- Create: `backend/app/components/graph/entity_resolver.py`

- [ ] **Step 1: Create entity_resolver.py**

Create `backend/app/components/graph/entity_resolver.py`:

```python
import re
import logging
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.graph import CanonicalEntity, EntityAlias, EntityResolutionLog

logger = logging.getLogger(__name__)

LEGAL_SUFFIXES = [
    r"\b(ltd|limited|inc|incorporated|corp|corporation|llc|pvt|private|gmbh)\b\.?$",
    r"\b(co|company|group|holdings|industries|technologies|services)\b\.?$",
]


def normalize_name(name: str) -> str:
    n = name.strip().lower()
    for pattern in LEGAL_SUFFIXES:
        n = re.sub(pattern, "", n).strip()
    n = re.sub(r"\s+", " ", n)
    return n


class EntityResolver:
    def __init__(self, db: Session):
        self.db = db

    def resolve(self, raw_name: str, extraction_id: int | None = None) -> tuple[CanonicalEntity, str, float]:
        raw_name = raw_name.strip()
        norm = normalize_name(raw_name)

        result, method, confidence = self._exact_match(norm)
        if result:
            self._log(extraction_id, raw_name, result.id, confidence, method)
            return result, method, confidence

        result, method, confidence = self._fuzzy_match(norm)
        if result:
            self._log(extraction_id, raw_name, result.id, confidence, method)
            self._record_alias(result.id, raw_name, "fuzzy", confidence)
            return result, method, confidence

        entity = self._create_entity(raw_name)
        self._log(extraction_id, raw_name, entity.id, 0.5, "new_entity")
        self._record_alias(entity.id, raw_name, "canonical", 1.0)
        return entity, "new_entity", 0.5

    def _exact_match(self, norm: str) -> tuple[CanonicalEntity | None, str | None, float]:
        alias = (
            self.db.query(EntityAlias)
            .filter(func.lower(EntityAlias.alias) == norm)
            .order_by(EntityAlias.confidence.desc())
            .first()
        )
        if alias:
            entity = self.db.query(CanonicalEntity).get(alias.canonical_id)
            if entity:
                return entity, "exact_alias", alias.confidence or 0.8

        entity = (
            self.db.query(CanonicalEntity)
            .filter(func.lower(CanonicalEntity.canonical_name) == norm)
            .first()
        )
        if entity:
            return entity, "exact_canonical", 1.0
        return None, None, 0.0

    def _fuzzy_match(self, norm: str) -> tuple[CanonicalEntity | None, str | None, float]:
        try:
            alias = (
                self.db.query(EntityAlias)
                .filter(EntityAlias.alias.op("%")(norm))
                .order_by(func.similarity(EntityAlias.alias, norm).desc())
                .limit(1)
                .first()
            )
            if alias:
                sim = self.db.execute(
                    func.similarity(alias.alias, norm)
                ).scalar()
                if sim and sim > 0.6:
                    entity = self.db.query(CanonicalEntity).get(alias.canonical_id)
                    if entity:
                        confidence = 0.7 if sim > 0.8 else 0.6
                        return entity, "fuzzy_alias", confidence
        except Exception:
            pass
        return None, None, 0.0

    def _create_entity(self, name: str) -> CanonicalEntity:
        entity = CanonicalEntity(canonical_name=name, entity_type="Unknown")
        self.db.add(entity)
        self.db.flush()
        logger.info(f"Created new entity: {name} (id={entity.id})")
        return entity

    def _record_alias(self, canonical_id: int, alias: str, alias_type: str, confidence: float):
        existing = (
            self.db.query(EntityAlias)
            .filter(
                EntityAlias.canonical_id == canonical_id,
                func.lower(EntityAlias.alias) == alias.lower(),
            )
            .first()
        )
        if existing:
            existing.last_seen_at = func.now()
            return
        self.db.add(EntityAlias(
            canonical_id=canonical_id, alias=alias,
            alias_type=alias_type, confidence=confidence,
            source="llm_discovered",
        ))

    def _log(self, extraction_id, raw_name, resolved_id, confidence, method):
        if extraction_id is None:
            return
        self.db.add(EntityResolutionLog(
            extraction_id=extraction_id, raw_name=raw_name,
            resolved_id=resolved_id, confidence=confidence, method=method,
        ))
```

---

### Task 6: Event Normalizer Component

**Files:**
- Create: `backend/app/components/graph/event_normalizer.py`

- [ ] **Step 1: Create event_normalizer.py**

Create `backend/app/components/graph/event_normalizer.py`:

```python
import logging
from sqlalchemy.orm import Session
from app.models.graph import EventType, GraphEvent

logger = logging.getLogger(__name__)

EVENT_KEYWORDS = {
    "MOU": ["mou", "memorandum of understanding", "signed an mou"],
    "PARTNERSHIP": ["partnership", "partnered", "strategic alliance", "collaboration", "joint venture", "jv"],
    "ACQUISITION": ["acquisition", "acquired", "buyout", "takeover", "stake purchase"],
    "MERGER": ["merger", "merged", "amalgamation"],
    "INVESTMENT": ["invested", "investment", "funding", "capital infusion"],
    "CONTRACT_AWARD": ["contract", "awarded", "order win"],
    "SUPPLY_AGREEMENT": ["supply agreement", "supplier", "supplies"],
    "DEFENSE_ORDER": ["defense order", "defence order", "ministry of defence"],
    "GOVERNMENT_APPROVAL": ["government approval", "sebi approval", "rbi approval"],
    "REGULATORY_ACTION": ["regulatory", "penalty", "fine", "investigation"],
    "EXECUTIVE_APPOINTMENT": ["appointed", "appointment", "named ceo", "named cfo"],
    "EXECUTIVE_RESIGNATION": ["resign", "resignation", "stepped down"],
    "REVENUE_GROWTH": ["revenue growth", "revenue increased", "sales grew"],
    "REVENUE_DECLINE": ["revenue decline", "revenue fell", "sales dropped"],
    "EARNINGS": ["earnings", "net profit", "net income", "quarterly result"],
    "DIVIDEND": ["dividend", "interim dividend"],
    "BUYBACK": ["buyback", "share buyback"],
    "FUNDRAISING": ["fundraising", "raised", "qip", "fpo"],
    "CAPACITY_EXPANSION": ["capacity expansion", "new plant"],
    "PRODUCT_LAUNCH": ["product launch", "launched", "new product"],
    "AI_PARTNERSHIP": ["ai partnership", "ai collaboration", "artificial intelligence"],
    "SEMICONDUCTOR_EXPANSION": ["semiconductor", "chip plant"],
    "ANALYST_UPGRADE": ["upgraded", "buy rating", "overweight"],
    "ANALYST_DOWNGRADE": ["downgraded", "sell rating", "underweight"],
    "MACRO_EVENT": ["gdp", "inflation", "interest rate", "fiscal policy"],
    "MARKET_MOVEMENT": ["market rally", "market fell", "nifty", "sensex"],
}

SENTIMENT_MAP = {"bullish": "Bullish", "bearish": "Bearish", "neutral": "Neutral", "positive": "Bullish", "negative": "Bearish", "mixed": "Neutral"}


class EventNormalizer:
    def __init__(self, db: Session):
        self.db = db
        self._type_cache = {t.event_type: t.id for t in db.query(EventType).all()}

    def classify(self, raw_category: str, context: str = "") -> tuple[str | None, str]:
        cat_lower = (raw_category or "").lower().strip()
        text_lower = (context or "").lower()
        for canonical, keywords in EVENT_KEYWORDS.items():
            for kw in keywords:
                if kw in cat_lower or kw in text_lower:
                    return canonical, kw
        for canonical in self._type_cache:
            if canonical.lower().replace("_", "") == cat_lower.replace(" ", "").replace("_", ""):
                return canonical, "enum_match"
        return None, "no_match"

    def record_event(self, extraction_id: int, news_id: int, event_type: str | None, event_type_raw: str | None, sentiment: str | None, confidence: float | None = None, importance: int | None = None, evidence_span: str | None = None) -> GraphEvent:
        type_id = self._type_cache.get(event_type) if event_type else None
        normalized_sentiment = SENTIMENT_MAP.get((sentiment or "").lower().strip())
        event = GraphEvent(extraction_id=extraction_id, news_id=news_id, event_type_id=type_id, event_type_raw=event_type_raw, sentiment=normalized_sentiment, confidence=confidence, importance=importance, evidence_span=evidence_span)
        self.db.add(event)
        return event
```

---

### Task 7: Graph Engine Component

**Files:**
- Create: `backend/app/components/graph/graph_engine.py`

- [ ] **Step 1: Create graph_engine.py**

Create `backend/app/components/graph/graph_engine.py`:

```python
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from app.models.graph import (
    CanonicalEntity, EntityAlias, Relationship, RelationshipEvidence,
    GraphEvent, EventType, EntityResolutionLog,
)
from app.components.graph.entity_resolver import EntityResolver
from app.components.graph.event_normalizer import EventNormalizer

logger = logging.getLogger(__name__)


class GraphEngine:
    def __init__(self, db: Session):
        self.db = db

    def process_extraction(self, extraction_id: int, news_id: int, raw_llm: dict | None, article_date: datetime | None = None):
        if not raw_llm:
            return
        resolver = EntityResolver(self.db)
        normalizer = EventNormalizer(self.db)
        entities_data = raw_llm.get("entities", [])
        relationships_data = raw_llm.get("relationships", [])
        resolved = []

        for ent in entities_data:
            raw_name = ent.get("entity_name", "")
            if not raw_name:
                continue
            entity, method, confidence = resolver.resolve(raw_name, extraction_id)
            resolved.append((entity, ent))
            if ent.get("entity_type") and entity.entity_type == "Unknown":
                entity.entity_type = ent["entity_type"]
            if ent.get("sector") and not entity.sector:
                entity.sector = ent["sector"]

            for ev in ent.get("events", []):
                raw_cat = ev.get("news_category", "")
                canonical_type, _ = normalizer.classify(raw_cat, raw_name)
                normalizer.record_event(
                    extraction_id=extraction_id, news_id=news_id,
                    event_type=canonical_type, event_type_raw=raw_cat,
                    sentiment=ev.get("sentiment"),
                    confidence=ev.get("confidence_score"),
                    importance=ev.get("importance_score"),
                    evidence_span=ev.get("evidence_span"),
                )

        for rel in relationships_data:
            src_raw = rel.get("source_entity", "")
            tgt_raw = rel.get("target_entity", "")
            rel_type = rel.get("relation", "related_to")
            if not src_raw or not tgt_raw:
                continue
            src_entity, _, sc = resolver.resolve(src_raw, extraction_id)
            tgt_entity, _, tc = resolver.resolve(tgt_raw, extraction_id)
            if src_entity.id != tgt_entity.id:
                self._upsert_relationship(src_entity.id, tgt_entity.id, rel_type, min(sc, tc), extraction_id, news_id)

        for i in range(len(resolved)):
            for j in range(i + 1, len(resolved)):
                e1, e2 = resolved[i][0], resolved[j][0]
                if e1.id != e2.id:
                    self._upsert_relationship(e1.id, e2.id, "co_occurs", 0.5, extraction_id, news_id)

    def _upsert_relationship(self, source_id: int, target_id: int, rel_type: str, confidence: float, extraction_id: int, news_id: int):
        existing = self.db.query(Relationship).filter(
            Relationship.source_entity == source_id,
            Relationship.target_entity == target_id,
            Relationship.relation_type == rel_type,
        ).first()
        now = datetime.now(timezone.utc)
        if existing:
            existing.weight = (existing.weight or 1) + 1
            existing.source_count = (existing.source_count or 1) + 1
            existing.last_seen_at = now
            existing.confidence = max(existing.confidence or 0, confidence)
            rel_id = existing.id
        else:
            rel = Relationship(source_entity=source_id, target_entity=target_id, relation_type=rel_type, weight=1, confidence=confidence, first_seen_at=now, last_seen_at=now, source_count=1)
            self.db.add(rel)
            self.db.flush()
            rel_id = rel.id
        self.db.add(RelationshipEvidence(relationship_id=rel_id, extraction_id=extraction_id, news_id=news_id, confidence=confidence))

    def get_subgraph(self, entity_name: str, layers: int = 2) -> dict:
        sql = text("""
            WITH RECURSIVE traversal AS (
                SELECT ce.id, ce.canonical_name AS name, ce.entity_type AS type, ce.sector, 0 AS dist
                FROM nse_canonical_entities ce WHERE ce.canonical_name = :name
                UNION
                SELECT DISTINCT ce2.id, ce2.canonical_name, ce2.entity_type, ce2.sector, t.dist + 1
                FROM traversal t
                JOIN nse_relationships r ON r.source_entity = t.id OR r.target_entity = t.id
                JOIN nse_canonical_entities ce2 ON ce2.id IN (r.source_entity, r.target_entity)
                WHERE t.dist < :layers AND ce2.id != t.id
            )
            SELECT DISTINCT id, name, type, sector, dist FROM traversal
        """)
        nodes = self.db.execute(sql, {"name": entity_name, "layers": layers}).fetchall()
        if not nodes:
            return {"nodes": [], "edges": [], "total_nodes": 0, "total_edges": 0}

        node_ids = [n[0] for n in nodes]
        node_list = [{"id": str(n[0]), "name": n[1], "type": n[2], "sector": n[3], "distance": n[4]} for n in nodes]
        edges = self.db.query(Relationship).filter(
            Relationship.source_entity.in_(node_ids),
            Relationship.target_entity.in_(node_ids),
        ).all()

        edge_list = []
        for e in edges:
            src = self.db.query(CanonicalEntity.canonical_name).filter(CanonicalEntity.id == e.source_entity).scalar()
            tgt = self.db.query(CanonicalEntity.canonical_name).filter(CanonicalEntity.id == e.target_entity).scalar()
            if src and tgt:
                edge_list.append({"source": src, "target": tgt, "relation_type": e.relation_type, "weight": e.weight or 1, "confidence": e.confidence or 0.5})

        tot_nodes = self.db.query(CanonicalEntity).count()
        tot_edges = self.db.query(Relationship).count()
        return {"nodes": node_list, "edges": edge_list, "total_nodes": tot_nodes, "total_edges": tot_edges}

    def get_entity_timeline(self, entity_name: str, days: int | None = None) -> dict:
        entity = self.db.query(CanonicalEntity).filter(CanonicalEntity.canonical_name == entity_name).first()
        if not entity:
            return {"entity": entity_name, "events": [], "total_events": 0, "date_range": None}

        subq = self.db.query(EntityResolutionLog.extraction_id).filter(EntityResolutionLog.resolved_id == entity.id).subquery()
        q = self.db.query(GraphEvent).filter(GraphEvent.extraction_id.in_(subq)).order_by(GraphEvent.created_at)

        if days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            q = q.filter(GraphEvent.created_at >= cutoff)

        events = q.all()
        event_list = []
        for ev in events:
            et_name = None
            if ev.event_type_id:
                et = self.db.query(EventType).get(ev.event_type_id)
                et_name = et.event_type if et else None
            event_list.append({
                "id": ev.id, "title": ev.event_type_raw or et_name or "",
                "timestamp": ev.created_at.isoformat() if ev.created_at else "",
                "event_type": et_name or ev.event_type_raw or "",
                "sentiment": ev.sentiment, "confidence": ev.confidence,
                "evidence_span": ev.evidence_span, "news_id": ev.news_id,
            })

        date_range = {"start": event_list[0]["timestamp"], "end": event_list[-1]["timestamp"]} if event_list else None
        return {"entity": entity_name, "events": event_list, "total_events": len(event_list), "date_range": date_range}
```

---

### Task 8: Propagation Engine (Phase 2)

**Files:**
- Create: `backend/app/components/graph/propagation.py`

- [ ] **Step 1: Create propagation.py**

Create `backend/app/components/graph/propagation.py`:

```python
import logging
from collections import deque
from sqlalchemy.orm import Session
from app.models.graph import CanonicalEntity, Relationship

logger = logging.getLogger(__name__)
DECAY = 0.5
MIN_CONFIDENCE = 0.3


class PropagationEngine:
    def __init__(self, db: Session):
        self.db = db

    def compute_propagation(self, source_name: str, max_hops: int = 3) -> list[dict]:
        source = self.db.query(CanonicalEntity).filter(CanonicalEntity.canonical_name == source_name).first()
        if not source:
            return []

        visited = {source.id: 0}
        scores = {source.id: 1.0}
        paths = {source.id: [source_name]}
        queue = deque([source.id])

        while queue:
            current = queue.popleft()
            cur_dist = visited[current]
            if cur_dist >= max_hops:
                continue
            edges = self.db.query(Relationship).filter(
                (Relationship.source_entity == current) | (Relationship.target_entity == current)
            ).all()
            for edge in edges:
                neighbor = edge.target_entity if edge.source_entity == current else edge.source_entity
                if neighbor not in visited or visited[neighbor] > cur_dist + 1:
                    visited[neighbor] = cur_dist + 1
                    decay = DECAY ** (cur_dist + 1)
                    score = scores[current] * (edge.confidence or 0.5) * decay
                    scores[neighbor] = score
                    n_name = self.db.query(CanonicalEntity.canonical_name).filter(CanonicalEntity.id == neighbor).scalar() or str(neighbor)
                    paths[neighbor] = list(paths[current]) + [n_name]
                    if neighbor not in visited:
                        queue.append(neighbor)

        results = []
        for eid, sc in scores.items():
            if eid == source.id or sc < MIN_CONFIDENCE:
                continue
            name = self.db.query(CanonicalEntity.canonical_name).filter(CanonicalEntity.id == eid).scalar()
            if name:
                results.append({"source": source_name, "target": name, "score": round(sc, 4), "path": paths.get(eid, []), "hops": visited.get(eid, 0), "decay": DECAY ** visited.get(eid, 1)})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results
```

---

### Task 9: Analytics Component (Phase 2)

**Files:**
- Create: `backend/app/components/graph/analytics.py`

- [ ] **Step 1: Create analytics.py**

Create `backend/app/components/graph/analytics.py`:

```python
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from app.models.graph import CanonicalEntity, Relationship, GraphMetric, GraphEvent, EntityResolutionLog, EventType

logger = logging.getLogger(__name__)


class GraphAnalytics:
    def __init__(self, db: Session):
        self.db = db

    def compute_centrality(self):
        total = self.db.query(CanonicalEntity).count()
        if total == 0:
            return
        subq = self.db.query(Relationship.source_entity, func.count().label("deg")).group_by(Relationship.source_entity).subquery()
        self.db.execute(text("""
            INSERT INTO nse_graph_metrics (entity_id, degree_centrality, computed_at)
            SELECT ce.id, COALESCE(sub.deg, 0)::float / :total, NOW()
            FROM nse_canonical_entities ce LEFT JOIN subq sub ON sub.source_entity = ce.id
            ON CONFLICT (entity_id) DO UPDATE SET degree_centrality = EXCLUDED.degree_centrality, computed_at = NOW()
        """), {"total": total})
        self.db.commit()

    def compute_mention_velocity(self):
        week = datetime.now(timezone.utc) - timedelta(days=7)
        subq = self.db.query(EntityResolutionLog.resolved_id.label("eid"), func.count().label("cnt")).filter(EntityResolutionLog.created_at >= week).group_by(EntityResolutionLog.resolved_id).subquery()
        self.db.execute(text("""
            INSERT INTO nse_graph_metrics (entity_id, mention_velocity, computed_at)
            SELECT ce.id, COALESCE(sub.cnt, 0), NOW()
            FROM nse_canonical_entities ce LEFT JOIN subq sub ON sub.eid = ce.id
            ON CONFLICT (entity_id) DO UPDATE SET mention_velocity = EXCLUDED.mention_velocity, computed_at = NOW()
        """))
        self.db.commit()

    def find_anomalies(self, hours: int = 24) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = self.db.query(Relationship).filter(Relationship.first_seen_at >= cutoff).order_by(Relationship.first_seen_at.desc()).limit(50).all()
        results = []
        for rel in recent:
            src = self.db.query(CanonicalEntity).get(rel.source_entity)
            tgt = self.db.query(CanonicalEntity).get(rel.target_entity)
            if src and tgt:
                results.append({"source": src.canonical_name, "target": tgt.canonical_name, "relation_type": rel.relation_type, "confidence": rel.confidence, "first_seen": rel.first_seen_at.isoformat() if rel.first_seen_at else None})
        return results

    def find_rising_entities(self, limit: int = 20) -> list[dict]:
        week = datetime.now(timezone.utc) - timedelta(days=7)
        month = datetime.now(timezone.utc) - timedelta(days=30)
        recent = self.db.query(EntityResolutionLog.resolved_id.label("eid"), func.count().label("cnt")).filter(EntityResolutionLog.created_at >= week).group_by(EntityResolutionLog.resolved_id).subquery()
        prev = self.db.query(EntityResolutionLog.resolved_id.label("eid"), func.count().label("cnt")).filter(EntityResolutionLog.created_at >= month, EntityResolutionLog.created_at < week).group_by(EntityResolutionLog.resolved_id).subquery()
        rows = self.db.execute(text("""
            SELECT ce.canonical_name, ce.entity_type, COALESCE(r.cnt, 0), COALESCE(p.cnt, 0)
            FROM nse_canonical_entities ce
            LEFT JOIN recent r ON r.eid = ce.id
            LEFT JOIN prev p ON p.eid = ce.id
            WHERE COALESCE(r.cnt, 0) > COALESCE(p.cnt, 0) * 2 AND COALESCE(p.cnt, 0) >= 1
            ORDER BY (COALESCE(r.cnt, 0) - COALESCE(p.cnt, 0)) DESC LIMIT :lim
        """), {"lim": limit}).fetchall()
        return [{"name": r[0], "type": r[1], "recent_mentions": r[2], "previous_mentions": r[3]} for r in rows]

    def get_stats(self) -> dict:
        te = self.db.query(CanonicalEntity).count()
        tr = self.db.query(Relationship).count()
        tgev = self.db.query(GraphEvent).count()
        ta = self.db.query(EntityResolutionLog.extraction_id).distinct().count()
        types = self.db.query(CanonicalEntity.entity_type, func.count().label("c")).group_by(CanonicalEntity.entity_type).order_by(func.count().desc()).limit(10).all()
        top = self.db.query(CanonicalEntity.canonical_name, CanonicalEntity.entity_type, GraphMetric.degree_centrality, GraphMetric.mention_velocity).join(GraphMetric, GraphMetric.entity_id == CanonicalEntity.id).order_by(GraphMetric.degree_centrality.desc().nullslast()).limit(20).all()
        return {
            "total_entities": te, "total_relationships": tr, "total_events": tgev, "total_articles_processed": ta,
            "entity_types": {t[0]: t[1] for t in types},
            "top_entities": [{"name": e[0], "type": e[1], "centrality": float(e[2] or 0), "velocity": float(e[3] or 0)} for e in top],
        }
```

---

### Task 10: Pipeline Orchestrator

**Files:**
- Create: `backend/app/components/graph/pipeline.py`

- [ ] **Step 1: Create pipeline.py**

Create `backend/app/components/graph/pipeline.py`:

```python
import asyncio
import logging
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.news import NewsExtraction
from app.components.graph.json_repair import parse_llm_raw
from app.components.graph.graph_engine import GraphEngine
from app.utils.redis_cache import cache_get, cache_set

logger = logging.getLogger(__name__)
CURSOR_KEY = "graph:pipeline:last_extraction_id"
BATCH_SIZE = 10
POLL_SECONDS = 60


class GraphPipeline:
    def __init__(self):
        self._running = False
        self._task = None

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Graph pipeline started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Graph pipeline stopped")

    async def _loop(self):
        while self._running:
            try:
                await self._process()
            except Exception as e:
                logger.error(f"Pipeline error: {e}", exc_info=True)
            await asyncio.sleep(POLL_SECONDS)

    async def _process(self):
        last_id = await cache_get(CURSOR_KEY)
        last_id = int(last_id) if last_id else 0
        db = SessionLocal()
        try:
            rows = db.query(NewsExtraction).filter(
                NewsExtraction.id > last_id,
                NewsExtraction.status == "completed",
                NewsExtraction.raw_llm_response.isnot(None),
            ).order_by(NewsExtraction.id).limit(BATCH_SIZE).all()
            if not rows:
                return
            engine = GraphEngine(db)
            for row in rows:
                parsed = parse_llm_raw(row.raw_llm_response)
                if parsed:
                    engine.process_extraction(row.id, row.news_id, parsed, row.completed_at)
                last_id = row.id
            db.commit()
            await cache_set(CURSOR_KEY, str(last_id))
            logger.info(f"Processed {len(rows)} extractions, cursor={last_id}")
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
```

---

### Task 11: Graph Service (Business Logic Layer)

**Files:**
- Create: `backend/app/services/graph_service.py`

- [ ] **Step 1: Create graph_service.py**

Create `backend/app/services/graph_service.py`:

```python
from sqlalchemy.orm import Session
from app.models.graph import CanonicalEntity, EntityAlias, GraphEvent, EventType, EntityResolutionLog
from app.components.graph.graph_engine import GraphEngine
from app.components.graph.propagation import PropagationEngine
from app.components.graph.analytics import GraphAnalytics


class GraphService:
    def __init__(self, db: Session):
        self.db = db
        self.engine = GraphEngine(db)

    def list_entities(self, query: str | None = None, page: int = 1, per_page: int = 20):
        q = self.db.query(CanonicalEntity)
        if query:
            q = q.filter(CanonicalEntity.canonical_name.ilike(f"%{query}%"))
        total = q.count()
        items = q.order_by(CanonicalEntity.canonical_name).offset((page - 1) * per_page).limit(per_page).all()
        return items, total

    def get_entity(self, entity_id: int) -> CanonicalEntity | None:
        return self.db.query(CanonicalEntity).get(entity_id)

    def create_entity(self, data: dict) -> CanonicalEntity:
        e = CanonicalEntity(**data)
        self.db.add(e)
        self.db.commit()
        self.db.refresh(e)
        return e

    def update_entity(self, entity_id: int, data: dict) -> CanonicalEntity | None:
        e = self.db.query(CanonicalEntity).get(entity_id)
        if not e:
            return None
        for k, v in data.items():
            if v is not None:
                setattr(e, k, v)
        self.db.commit()
        self.db.refresh(e)
        return e

    def delete_entity(self, entity_id: int) -> bool:
        e = self.db.query(CanonicalEntity).get(entity_id)
        if not e:
            return False
        self.db.delete(e)
        self.db.commit()
        return True

    def get_aliases(self, entity_id: int):
        return self.db.query(EntityAlias).filter(EntityAlias.canonical_id == entity_id).all()

    def create_alias(self, data: dict) -> EntityAlias:
        a = EntityAlias(**data)
        self.db.add(a)
        self.db.commit()
        self.db.refresh(a)
        return a

    def update_alias(self, alias_id: int, data: dict) -> EntityAlias | None:
        a = self.db.query(EntityAlias).get(alias_id)
        if not a:
            return None
        for k, v in data.items():
            if v is not None:
                setattr(a, k, v)
        self.db.commit()
        self.db.refresh(a)
        return a

    def delete_alias(self, alias_id: int) -> bool:
        a = self.db.query(EntityAlias).get(alias_id)
        if not a:
            return False
        self.db.delete(a)
        self.db.commit()
        return True

    def explore(self, entity: str, layers: int = 2):
        return self.engine.get_subgraph(entity, layers)

    def timeline(self, entity_name: str, days: int | None = None):
        return self.engine.get_entity_timeline(entity_name, days)

    def events(self, entity_name: str | None = None, event_type: str | None = None, page: int = 1, per_page: int = 20):
        q = self.db.query(GraphEvent)
        if entity_name:
            e = self.db.query(CanonicalEntity).filter(CanonicalEntity.canonical_name == entity_name).first()
            if e:
                q = q.filter(GraphEvent.extraction_id.in_(self.db.query(EntityResolutionLog.extraction_id).filter(EntityResolutionLog.resolved_id == e.id)))
        if event_type:
            et = self.db.query(EventType).filter(EventType.event_type == event_type).first()
            if et:
                q = q.filter(GraphEvent.event_type_id == et.id)
        total = q.count()
        items = q.order_by(GraphEvent.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
        return items, total

    def get_event_types(self):
        return self.db.query(EventType).filter(EventType.is_active == True).all()

    def propagation(self, source: str, hops: int = 3):
        return PropagationEngine(self.db).compute_propagation(source, hops)

    def stats(self):
        return GraphAnalytics(self.db).get_stats()

    def anomalies(self, hours: int = 24):
        return GraphAnalytics(self.db).find_anomalies(hours)

    def rising(self, limit: int = 20):
        return GraphAnalytics(self.db).find_rising_entities(limit)
```

---

### Task 12: API Routes — /api/v1/graph/*

**Files:**
- Create: `backend/app/api/v1/graph.py`
- Modify: `backend/app/api/v1/__init__.py`

- [ ] **Step 1: Create graph.py**

Create `backend/app/api/v1/graph.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.graph_service import GraphService
from app.schemas.graph import (
    CanonicalEntityOut, CanonicalEntityDetail, CanonicalEntityCreate, CanonicalEntityUpdate,
    EntityAliasOut, EntityAliasCreate, EntityAliasUpdate,
    SubgraphOut, TimelineOut, GraphEventOut, EventTypeOut, StatsOut,
)

router = APIRouter(tags=["Graph Intelligence"])

@router.get("/entities")
def list_entities(q: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    s = GraphService(db)
    items, total = s.list_entities(q, page, per_page)
    pages = max(1, (total + per_page - 1) // per_page)
    return {"items": [CanonicalEntityOut.model_validate(i) for i in items], "total": total, "page": page, "per_page": per_page, "pages": pages, "has_next": page < pages, "has_prev": page > 1}

@router.get("/entities/{entity_id}", response_model=CanonicalEntityDetail)
def get_entity(entity_id: int, db: Session = Depends(get_db)):
    s = GraphService(db)
    e = s.get_entity(entity_id)
    if not e:
        raise HTTPException(404, "Entity not found")
    aliases = s.get_aliases(entity_id)
    d = CanonicalEntityDetail.model_validate(e)
    d.aliases = [EntityAliasOut.model_validate(a) for a in aliases]
    return d

@router.post("/entities", response_model=CanonicalEntityOut, status_code=201)
def create_entity(data: CanonicalEntityCreate, db: Session = Depends(get_db)):
    return CanonicalEntityOut.model_validate(GraphService(db).create_entity(data.model_dump()))

@router.put("/entities/{entity_id}", response_model=CanonicalEntityOut)
def update_entity(entity_id: int, data: CanonicalEntityUpdate, db: Session = Depends(get_db)):
    e = GraphService(db).update_entity(entity_id, data.model_dump(exclude_none=True))
    if not e:
        raise HTTPException(404, "Entity not found")
    return CanonicalEntityOut.model_validate(e)

@router.delete("/entities/{entity_id}", status_code=204)
def delete_entity(entity_id: int, db: Session = Depends(get_db)):
    if not GraphService(db).delete_entity(entity_id):
        raise HTTPException(404, "Entity not found")

@router.get("/entities/{entity_id}/aliases", response_model=list[EntityAliasOut])
def list_aliases(entity_id: int, db: Session = Depends(get_db)):
    return [EntityAliasOut.model_validate(a) for a in GraphService(db).get_aliases(entity_id)]

@router.post("/aliases", response_model=EntityAliasOut, status_code=201)
def create_alias(data: EntityAliasCreate, db: Session = Depends(get_db)):
    return EntityAliasOut.model_validate(GraphService(db).create_alias(data.model_dump()))

@router.put("/aliases/{alias_id}", response_model=EntityAliasOut)
def update_alias(alias_id: int, data: EntityAliasUpdate, db: Session = Depends(get_db)):
    a = GraphService(db).update_alias(alias_id, data.model_dump(exclude_none=True))
    if not a:
        raise HTTPException(404, "Alias not found")
    return EntityAliasOut.model_validate(a)

@router.delete("/aliases/{alias_id}", status_code=204)
def delete_alias(alias_id: int, db: Session = Depends(get_db)):
    if not GraphService(db).delete_alias(alias_id):
        raise HTTPException(404, "Alias not found")

@router.get("/explore", response_model=SubgraphOut)
def explore(entity: str = Query(...), layers: int = Query(2, ge=1, le=3), db: Session = Depends(get_db)):
    return GraphService(db).explore(entity, layers)

@router.get("/timeline/{entity_name}", response_model=TimelineOut)
def timeline(entity_name: str, days: int | None = Query(None), db: Session = Depends(get_db)):
    return GraphService(db).timeline(entity_name, days)

@router.get("/events")
def list_events(entity: str | None = Query(None), event_type: str | None = Query(None), page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    s = GraphService(db)
    items, total = s.events(entity, event_type, page, per_page)
    pages = max(1, (total + per_page - 1) // per_page)
    return {"items": [GraphEventOut.model_validate(i) for i in items], "total": total, "page": page, "per_page": per_page, "pages": pages, "has_next": page < pages, "has_prev": page > 1}

@router.get("/event-types", response_model=list[EventTypeOut])
def list_event_types(db: Session = Depends(get_db)):
    return [EventTypeOut.model_validate(et) for et in GraphService(db).get_event_types()]

@router.get("/stats", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)):
    return GraphService(db).stats()

@router.get("/anomalies")
def get_anomalies(hours: int = Query(24, ge=1), db: Session = Depends(get_db)):
    return GraphService(db).anomalies(hours)

@router.get("/rising")
def get_rising(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return GraphService(db).rising(limit)

@router.get("/propagation")
def get_propagation(source: str = Query(...), hops: int = Query(3, ge=1, le=5), db: Session = Depends(get_db)):
    return GraphService(db).propagation(source, hops)
```

- [ ] **Step 2: Register routes in __init__.py**

Add to `backend/app/api/v1/__init__.py`:
```python
from app.api.v1.graph import router as graph_router
api_router.include_router(graph_router, prefix="/graph", tags=["Graph Intelligence"])
```

---

### Task 13: Frontend Graph API Service

**Files:**
- Create: `frontend/src/app/shared/services/graph.service.ts`

- [ ] **Step 1: Create graph service**

Create `frontend/src/app/shared/services/graph.service.ts`:

```typescript
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

const API = `${environment.apiUrl}/api/v1/graph`;

export interface CanonicalEntity {
  id: number;
  canonical_name: string;
  entity_type: string;
  sector: string | null;
  ticker: string | null;
  confidence: number | null;
  created_at: string | null;
}

export interface CanonicalEntityDetail extends CanonicalEntity {
  aliases: EntityAlias[];
  metrics: GraphMetric | null;
}

export interface EntityAlias {
  id: number;
  canonical_id: number;
  alias: string;
  alias_type: string;
  confidence: number | null;
  source: string | null;
}

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  sector: string | null;
  centrality: number;
  mention_count: number;
  distance: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation_type: string;
  weight: number;
  confidence: number;
}

export interface Subgraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  total_nodes: number;
  total_edges: number;
}

export interface TimelineEvent {
  id: number;
  title: string;
  timestamp: string;
  event_type: string;
  sentiment: string | null;
  confidence: number | null;
  evidence_span: string | null;
  news_id: number;
}

export interface Timeline {
  entity: string;
  events: TimelineEvent[];
  total_events: number;
  date_range: { start: string; end: string } | null;
}

export interface GraphStats {
  total_entities: number;
  total_relationships: number;
  total_events: number;
  total_articles_processed: number;
  entity_types: Record<string, number>;
  top_entities: { name: string; type: string; centrality: number; velocity: number }[];
}

@Injectable({ providedIn: 'root' })
export class GraphService {
  private http = inject(HttpClient);

  listEntities(q?: string, page = 1, perPage = 20): Observable<any> {
    let p = new HttpParams().set('page', page).set('per_page', perPage);
    if (q) p = p.set('q', q);
    return this.http.get(`${API}/entities`, { params: p });
  }

  getEntity(id: number): Observable<CanonicalEntityDetail> {
    return this.http.get<CanonicalEntityDetail>(`${API}/entities/${id}`);
  }

  createEntity(data: Partial<CanonicalEntity>): Observable<CanonicalEntity> {
    return this.http.post<CanonicalEntity>(`${API}/entities`, data);
  }

  updateEntity(id: number, data: Partial<CanonicalEntity>): Observable<CanonicalEntity> {
    return this.http.put<CanonicalEntity>(`${API}/entities/${id}`, data);
  }

  deleteEntity(id: number): Observable<void> {
    return this.http.delete<void>(`${API}/entities/${id}`);
  }

  listAliases(entityId: number): Observable<EntityAlias[]> {
    return this.http.get<EntityAlias[]>(`${API}/entities/${entityId}/aliases`);
  }

  createAlias(data: Partial<EntityAlias>): Observable<EntityAlias> {
    return this.http.post<EntityAlias>(`${API}/aliases`, data);
  }

  updateAlias(id: number, data: Partial<EntityAlias>): Observable<EntityAlias> {
    return this.http.put<EntityAlias>(`${API}/aliases/${id}`, data);
  }

  deleteAlias(id: number): Observable<void> {
    return this.http.delete<void>(`${API}/aliases/${id}`);
  }

  explore(entity: string, layers = 2): Observable<Subgraph> {
    return this.http.get<Subgraph>(`${API}/explore`, { params: new HttpParams().set('entity', entity).set('layers', layers) });
  }

  getTimeline(entityName: string, days?: number): Observable<Timeline> {
    let p = new HttpParams();
    if (days) p = p.set('days', days);
    return this.http.get<Timeline>(`${API}/timeline/${encodeURIComponent(entityName)}`, { params: p });
  }

  listEvents(entity?: string, eventType?: string, page = 1, perPage = 20): Observable<any> {
    let p = new HttpParams().set('page', page).set('per_page', perPage);
    if (entity) p = p.set('entity', entity);
    if (eventType) p = p.set('event_type', eventType);
    return this.http.get(`${API}/events`, { params: p });
  }

  getEventTypes(): Observable<any[]> {
    return this.http.get<any[]>(`${API}/event-types`);
  }

  getStats(): Observable<GraphStats> {
    return this.http.get<GraphStats>(`${API}/stats`);
  }

  getAnomalies(hours = 24): Observable<any[]> {
    return this.http.get<any[]>(`${API}/anomalies`, { params: new HttpParams().set('hours', hours) });
  }

  getRising(limit = 20): Observable<any[]> {
    return this.http.get<any[]>(`${API}/rising`, { params: new HttpParams().set('limit', limit) });
  }

  getPropagation(source: string, hops = 3): Observable<any[]> {
    return this.http.get<any[]>(`${API}/propagation`, { params: new HttpParams().set('source', source).set('hops', hops) });
  }
}
```

---

### Task 14: Frontend Graph Canvas Component (Cytoscape.js)

**Files:**
- Create: `frontend/src/app/pages/kiyannet/components/graph-canvas/graph-canvas.ts`
- Create: `frontend/src/app/pages/kiyannet/components/graph-canvas/graph-canvas.html`
- Create: `frontend/src/app/pages/kiyannet/components/graph-canvas/graph-canvas.scss`

- [ ] **Step 1: Create graph-canvas component**

Run `ng generate component pages/kiyannet/components/graph-canvas --standalone` inside frontend, then modify files.

Create `graph-canvas.ts`:
```typescript
import { Component, ElementRef, Input, OnChanges, ViewChild, AfterViewInit, signal } from '@angular/core';
import cytoscape from 'cytoscape';

export interface GraphData {
  nodes: any[];
  edges: any[];
}

@Component({
  selector: 'app-graph-canvas',
  standalone: true,
  template: `<div #container class="graph-container" (window:resize)="onResize()"></div>`,
  styles: [`.graph-container { width: 100%; height: 100%; min-height: 400px; }`],
})
export class GraphCanvas implements AfterViewInit, OnChanges {
  @ViewChild('container') container!: ElementRef;
  @Input() data: GraphData | null = null;
  @Input() highlightEntity: string | null = null;

  private cy: cytoscape.Core | null = null;

  ngAfterViewInit() {
    this.initCytoscape();
  }

  ngOnChanges() {
    if (this.cy) this.loadData();
  }

  private initCytoscape() {
    const el = this.container.nativeElement;
    this.cy = cytoscape({
      container: el,
      style: [
        { selector: 'node', style: { 'background-color': '#58a6ff', label: 'data(name)', 'font-size': '10px', color: '#c9d1d9', 'text-valign': 'bottom', 'text-halign': 'center', 'text-margin-y': 4 } },
        { selector: 'edge', style: { width: 'mapData(weight, 1, 10, 0.5, 3)', 'line-color': '#30363d', 'target-arrow-color': '#58a6ff', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier', opacity: 0.6 } },
        { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#f0883e' } },
        { selector: '.highlighted', style: { 'background-color': '#f0883e', 'border-width': 3, 'border-color': '#ffd700' } },
      ],
      layout: { name: 'cose', animate: true, nodeRepulsion: 8000, idealEdgeLength: 120 },
      wheelSensitivity: 0.3,
    });
    this.loadData();
  }

  private loadData() {
    if (!this.cy || !this.data) return;
    this.cy.elements().remove();
    const elements: any[] = [];
    for (const n of this.data.nodes) {
      elements.push({ group: 'nodes', data: { id: n.id, name: n.name, type: n.type, centrality: n.centrality, distance: n.distance } });
    }
    for (const e of this.data.edges) {
      elements.push({ group: 'edges', data: { source: e.source, target: e.target, weight: e.weight, label: e.relation_type } });
    }
    this.cy.add(elements);
    this.cy.layout({ name: 'cose', animate: true, nodeRepulsion: 8000, idealEdgeLength: 120 }).run();
    this.cy.fit(undefined, 50);
  }
}
```

---

### Task 15: Frontend Entity Panel Component

**Files:**
- Create: frontend components for entity-panel, entity-list, command-bar, temporal-scrubber

(This task covers the remaining frontend structural components. Implement each as a standalone Angular component.)

- [ ] **Step 1: Create entity-panel component** — shows entity detail in right sidebar
- [ ] **Step 2: Create entity-list component** — left sidebar with searchable entity list
- [ ] **Step 3: Create command-bar component** — Bloomberg-style search bar
- [ ] **Step 4: Create temporal-scrubber component** — timeline slider

Run: `ng generate component pages/kiyannet/components/entity-panel --standalone` etc. Each component uses GraphService to fetch data.

---

### Task 16: Frontend Main Kiyannet Terminal Layout

**Files:**
- Modify: `frontend/src/app/pages/kiyannet/kiyannet.ts`, `kiyannet.html`, `kiyannet.scss`

- [ ] **Step 1: Redesign kiyannet.ts to host tabs**

Update `kiyannet.ts`:
```typescript
import { Component, signal } from '@angular/core';
import { GraphCanvas } from './components/graph-canvas/graph-canvas';

@Component({
  selector: 'app-kiyannet',
  standalone: true,
  imports: [GraphCanvas],
  templateUrl: './kiyannet.html',
  styleUrl: './kiyannet.scss',
})
export class Kiyannet {
  activeTab = signal('graph');
  tabs = [
    { id: 'graph', label: 'Graph Explorer', icon: 'fa-share-alt' },
    { id: 'timeline', label: 'Timeline', icon: 'fa-clock-o' },
    { id: 'entities', label: 'Entities', icon: 'fa-database' },
    { id: 'propagation', label: 'Propagation', icon: 'fa-random' },
    { id: 'alerts', label: 'Alerts', icon: 'fa-bell' },
  ];

  setTab(id: string) { this.activeTab.set(id); }
}
```

Update `kiyannet.html` to the three-panel terminal layout with tabs, left sidebar, center graph, right detail panel, and temporal scrubber.

---

### Task 17: App Router — Register new kiyannet sub-routes

**Files:**
- Modify: `frontend/src/app/app.routes.ts`

- [ ] **Step 1: Update routing for kiyannet sub-tabs**

No new routes needed — the tabs are in-component. The existing `/kiyannet` route continues to load the new Kiyannet terminal component.

---

### Task 18: Bootstrap Pipeline in Backend Main

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Start GraphPipeline on app startup**

Add to `backend/app/main.py` lifespan:
```python
from app.components.graph.pipeline import GraphPipeline

_graph_pipeline = GraphPipeline()

# In lifespan startup:
await _graph_pipeline.start()

# In lifespan shutdown:
await _graph_pipeline.stop()
```

---

### Self-Review Checklist

1. [ ] **Spec coverage**: Every spec requirement maps to a task above:
   - Entity resolution (Tasks 1-5) ✓
   - Event normalization (Task 6) ✓
   - Graph engine (Task 7) ✓
   - Propagation engine (Task 8) ✓
   - Analytics (Task 9) ✓
   - Pipeline orchestrator (Task 10) ✓
   - Business logic service (Task 11) ✓
   - API routes (Task 12) ✓
   - Frontend service (Task 13) ✓
   - Frontend graph viz (Task 14) ✓
   - Frontend components (Task 15) ✓
   - Terminal layout (Task 16) ✓
   - Routing (Task 17) ✓
   - Bootstrap pipeline (Task 18) ✓

2. [ ] **No placeholders** — all code is concrete
3. [ ] **Type consistency** — check that function signatures match across tasks
4. [ ] **Correct file paths** — all paths match the existing project structure
