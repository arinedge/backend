# Event Chain Intelligence Engine — Design Spec

## Overview

Build the core intelligence engine for the ArinEdge platform. Transforms unstructured financial news into a resolved, temporal, multi-hop relationship graph that powers entity intelligence, event chain analysis, and propagation insights.

## Architecture

**Approach**: Centralized within the existing **backend** FastAPI service (not a new microservice).

```
backend/app/components/graph/
├── __init__.py
├── entity_resolver.py       # Entity resolution + alias mapping
├── event_normalizer.py      # Event taxonomy normalization
├── graph_engine.py          # Graph construction + traversal
├── propagation.py           # Influence propagation engine (Phase 2)
├── analytics.py             # PageRank, centrality, clustering
├── json_repair.py           # Malformed JSON repair layer
└── pipeline.py              # Ingestion pipeline orchestrator
```

**Architecture flow**:
```
News Article → LLM Extraction → [json_repair] → [entity_resolver]
  → [event_normalizer] → [graph_engine] → [analytics]
  → Redis cache → API → Cytoscape.js frontend
```

**Key decisions**:
- PostgreSQL-only hybrid (no Neo4j) — recursive CTEs + pgvector + materialized views
- Incremental processing via cursor tracking (last processed extraction_id)
- Redis for hot-path caching of graph projections
- JSON repair layer handles malformed LLM output

## Database Schema

All new tables use `nse_` prefix.

### Entity Resolution

```sql
nse_canonical_entities (
  id              BIGSERIAL PRIMARY KEY,
  canonical_name  TEXT NOT NULL UNIQUE,
  entity_type     TEXT NOT NULL,
  sector          TEXT,
  ticker          TEXT,
  isin            TEXT,
  description     TEXT,
  metadata        JSONB,
  confidence      FLOAT DEFAULT 1.0,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

nse_entity_aliases (
  id              BIGSERIAL PRIMARY KEY,
  canonical_id    BIGINT REFERENCES nse_canonical_entities(id),
  alias           TEXT NOT NULL,
  alias_type      TEXT NOT NULL,    -- 'abbreviation','partial','ticker','phonetic','embedding','manual'
  confidence      FLOAT DEFAULT 0.8,
  source          TEXT,             -- 'manual','llm_discovered','nse_import'
  first_seen_at   TIMESTAMPTZ DEFAULT NOW(),
  last_seen_at    TIMESTAMPTZ DEFAULT NOW()
);

nse_entity_embeddings (
  id              BIGSERIAL PRIMARY KEY,
  canonical_id    BIGINT REFERENCES nse_canonical_entities(id),
  embedding       VECTOR(384),
  model           TEXT,
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

nse_entity_resolution_log (
  id              BIGSERIAL PRIMARY KEY,
  extraction_id   INTEGER REFERENCES news_extraction(id),
  raw_name        TEXT NOT NULL,
  resolved_id     BIGINT REFERENCES nse_canonical_entities(id),
  confidence      FLOAT,
  method          TEXT,             -- 'exact','fuzzy','embedding','manual'
  created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### Event Normalization

```sql
nse_event_types (
  id              SERIAL PRIMARY KEY,
  event_type      TEXT NOT NULL UNIQUE,
  parent_type     TEXT,
  description     TEXT,
  is_active       BOOLEAN DEFAULT TRUE
);

nse_events (
  id              BIGSERIAL PRIMARY KEY,
  extraction_id   INTEGER REFERENCES news_extraction(id),
  news_id         INTEGER REFERENCES market_news(id),
  event_type_id   INTEGER REFERENCES nse_event_types(id),
  event_type_raw  TEXT,
  sentiment       TEXT,
  confidence      FLOAT,
  importance      INTEGER,
  evidence_span   TEXT,
  event_date      DATE,
  article_date    TIMESTAMPTZ,
  metadata        JSONB,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### Graph

```sql
nse_relationships (
  id              BIGSERIAL PRIMARY KEY,
  source_entity   BIGINT REFERENCES nse_canonical_entities(id),
  target_entity   BIGINT REFERENCES nse_canonical_entities(id),
  relation_type   TEXT NOT NULL,
  weight          FLOAT DEFAULT 1.0,
  confidence      FLOAT DEFAULT 0.5,
  first_seen_at   TIMESTAMPTZ,
  last_seen_at    TIMESTAMPTZ DEFAULT NOW(),
  source_count    INTEGER DEFAULT 1,
  metadata        JSONB
);

nse_relationship_evidence (
  id              BIGSERIAL PRIMARY KEY,
  relationship_id BIGINT REFERENCES nse_relationships(id),
  extraction_id   INTEGER REFERENCES news_extraction(id),
  news_id         INTEGER REFERENCES market_news(id),
  evidence_span   TEXT,
  confidence      FLOAT,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### Analytics

```sql
nse_graph_metrics (
  entity_id          BIGINT PRIMARY KEY REFERENCES nse_canonical_entities(id),
  pagerank           FLOAT DEFAULT 0.0,
  degree_centrality  FLOAT DEFAULT 0.0,
  betweenness        FLOAT DEFAULT 0.0,
  mention_velocity   FLOAT DEFAULT 0.0,
  sentiment_score    FLOAT DEFAULT 0.0,
  sentiment_velocity FLOAT DEFAULT 0.0,
  cluster_id         INTEGER,
  computed_at        TIMESTAMPTZ DEFAULT NOW()
);

nse_propagation_scores (
  source_id         BIGINT REFERENCES nse_canonical_entities(id),
  target_id         BIGINT REFERENCES nse_canonical_entities(id),
  propagation_score FLOAT,
  influence_path    TEXT[],
  hop_count         INTEGER,
  decay_factor      FLOAT,
  computed_at       TIMESTAMPTZ DEFAULT NOW()
);
```

**Indexes**:
- GIN trigram on `nse_entity_aliases.alias`
- IVFFlat on `nse_entity_embeddings.embedding`
- B-tree on `nse_relationships.(source_entity, target_entity)`
- B-tree on `nse_events.(news_id, extraction_id)`

## Entity Resolution Engine

Six-stage resolution pipeline:

| Stage | Method | Confidence |
|-------|--------|-----------|
| 1 | Normalize — lowercase, strip, remove legal suffixes | — |
| 2 | Exact match against `nse_entity_aliases` | 1.0 |
| 3 | Trigram fuzzy match (similarity > 0.8) | 0.9 |
| 4 | Embedding similarity via pgvector (distance < 0.1) | 0.85 |
| 5 | NSE ticker cross-reference | 0.95 |
| 6 | Create new canonical entity | 0.5 |

**Self-learning**: When multiple raw names resolve to the same canonical entity, new variants are automatically added as aliases with `llm_discovered` source.

**Manual overrides**: Users can add/edit/delete aliases from frontend. Manual aliases get `confidence = 1.0`, `source = 'manual'`, and take priority.

**Incremental processing**: Tracks `last_processed_id` in Redis. Polls `news_extraction` for new completed rows.

## Event Normalization

Maps inconsistent LLM categories to canonical event types:
```
"FINANCIALS" | "Revenue Growth" | "revenue growth" → REVENUE_GROWTH
"MARKET" | "Price Target" | "Analyst Upgrade"     → ANALYST_UPGRADE
"MOU" | "partnership" | "alliance"               → PARTNERSHIP
"acquisition" | "acquired" | "buyout"            → ACQUISITION
```

Uses keyword-based classifier with evidence logging. Follows same incremental cursor pattern.

## Canonical Event Types

```
MOU, PARTNERSHIP, ACQUISITION, MERGER, INVESTMENT,
CONTRACT_AWARD, SUPPLY_AGREEMENT, DEFENSE_ORDER,
GOVERNMENT_APPROVAL, REGULATORY_ACTION, BOARD_CHANGE,
EXECUTIVE_APPOINTMENT, EXECUTIVE_RESIGNATION,
REVENUE_GROWTH, REVENUE_DECLINE, EARNINGS,
DIVIDEND, BUYBACK, FUNDRAISING,
CAPACITY_EXPANSION, PLANT_LAUNCH, PRODUCT_LAUNCH,
EXPORT_DEAL, AI_PARTNERSHIP, SEMICONDUCTOR_EXPANSION,
PRICE_TARGET_CHANGE, ANALYST_UPGRADE, ANALYST_DOWNGRADE,
MACRO_EVENT, SECTOR_TREND, MARKET_MOVEMENT
```

## API Design

All routes under `/api/v1/graph`:

### Phase 1 — Core Intelligence
```
GET    /api/v1/graph/entities                   — List/search entities
GET    /api/v1/graph/entities/:id               — Entity 360° view
POST   /api/v1/graph/entities                   — Create canonical entity
PUT    /api/v1/graph/entities/:id               — Update entity
DELETE /api/v1/graph/entities/:id               — Soft-delete entity

GET    /api/v1/graph/entities/:id/aliases       — List aliases
POST   /api/v1/graph/aliases                    — Add alias
PUT    /api/v1/graph/aliases/:id                — Update alias
DELETE /api/v1/graph/aliases/:id                — Remove alias

GET    /api/v1/graph/entities/:id/events        — Entity events
GET    /api/v1/graph/explore                    — Subgraph exploration
GET    /api/v1/graph/connections                — Connecting articles
GET    /api/v1/graph/timeline/:entity_id        — Event timeline
GET    /api/v1/graph/events                     — Search events
GET    /api/v1/graph/event-types                — List event types
GET    /api/v1/graph/stats                      — Global stats
GET    /api/v1/graph/top                        — Top entities
GET    /api/v1/graph/path                       — Shortest path
```

### Phase 2 — Analytical Power
```
GET    /api/v1/graph/propagation                — Influence propagation
GET    /api/v1/graph/heatmap                    — Portfolio exposure map
GET    /api/v1/graph/anomalies                  — Unexpected new edges
GET    /api/v1/graph/clusters                   — Community clusters
GET    /api/v1/graph/rising                     — Rising entities
GET    /api/v1/graph/alerts                     — User alerts
POST   /api/v1/graph/alerts                     — Create alert
DELETE /api/v1/graph/alerts/:id
POST   /api/v1/graph/pipeline/backfill          — Trigger reprocess
GET    /api/v1/graph/pipeline/status            — Pipeline health
```

Consistent response format:
```json
{ "data": {}, "meta": { "page": 1, "total": 42, "processing_ms": 15 }, "error": null }
```

## Frontend Design

Route: `/kiyannet` — redesigned as Intelligence Terminal.

**Layout**: Three-panel design (left list, center graph, right detail) with tab bar and temporal scrubber.

**Tabs**:
1. **Graph Explorer** (Phase 1) — Cytoscape.js force-directed graph, entity search, layer selector, temporal scrubber
2. **Timeline** (Phase 1) — Horizontal event timeline, color-coded types, narrative thread detection
3. **Entity Management** (Phase 1) — Search/browse entities, manage aliases, manual override
4. **Clusters** (Phase 2) — Community detection visualization
5. **Propagation** (Phase 2) — Sankey-style influence flow
6. **Alerts** (Phase 2) — Alert configuration and feed
7. **Portfolio Heatmap** (Phase 2) — Supply chain exposure grid

**Frontend components**:
```
frontend/src/app/pages/kiyannet/
├── kiyannet.ts/html/scss          — Parent terminal layout
├── components/
│   ├── graph-canvas/              — Cytoscape.js wrapper
│   ├── entity-panel/              — Entity detail sidebar
│   ├── entity-list/               — Entity list panel
│   ├── timeline/                  — Timeline component
│   ├── command-bar/               — Bloomberg-style search
│   └── temporal-scrubber/         — Timeline slider
├── graph/                         — Graph Explorer tab
├── timeline/                      — Timeline tab
├── entities/                      — Entity Management tab
├── clusters/                      — Clusters tab (Phase 2)
├── propagation/                   — Propagation tab (Phase 2)
├── alerts/                        — Alerts tab (Phase 2)
├── heatmap/                       — Portfolio heatmap (Phase 2)
└── services/
    └── graph.service.ts           — API client for /api/v1/graph/*
```

Existing routes (`/kiyannet-news`, `/kiyannet-news/analytics/:id`, `/kiyannet-anomaly`) remain untouched.

## Incremental Pipeline

1. Redis cursor tracks `graph:pipeline:last_extraction_id`
2. Background worker polls `news_extraction WHERE id > cursor AND status = 'completed'`
3. Each row: JSON repair → entity resolution → event normalization → graph edge update
4. After batch: update cursor, invalidate affected Redis cache keys
5. Materialized views recompute on schedule (every 15 min) or on-demand

## Unique Features (built Phase 1+2)

1. **Entity Resolution + Manual Override** with full audit trail
2. **Indian Market DNA** — built for NSE securities, local entity resolution
3. **Sub-30-second ingestion lag** — streaming pipeline
4. **Temporal Graph Playback** — see relationship structure evolve
5. **Confidence-as-a-Feature** — every data point carries reliability score
6. **Anomaly Detection** — unexpected new edges flagged in real-time
7. **Portfolio Heatmap** — hidden supply chain exposures

## Phasing

| Phase | Scope | Timeline |
|-------|-------|----------|
| 1 | Entity resolution, event normalization, graph engine, timeline, entity management, search API, graph explorer frontend | Build now |
| 2 | Propagation engine, clusters, alerts, portfolio heatmap, anomaly detection, pipeline health | Build now |
| 3 | Graph ML prediction, narrative detection, leading indicators, B2B API | Future |

## Implementation Order

1. Database migrations (create all `nse_*` tables)
2. Backend models + schemas
3. `json_repair.py` — malformed JSON fixer
4. `entity_resolver.py` — resolution pipeline
5. `event_normalizer.py` — taxonomy mapper
6. `graph_engine.py` — graph construction + traversal
7. `pipeline.py` — orchestrator + cursor tracking
8. API routes (`/api/v1/graph/*`)
9. `graph.service.ts` — frontend API client
10. Frontend — `graph-canvas.component` (Cytoscape.js)
11. Frontend — `entity-panel`, `entity-list`, `command-bar`, `temporal-scrubber`
12. Frontend — Graph Explorer tab
13. Frontend — Timeline tab
14. Frontend — Entity Management tab
15. Phase 2: `propagation.py`
16. Phase 2: `analytics.py` (clustering, anomaly detection)
17. Phase 2: Propagation + Clusters + Alerts frontend tabs
18. Phase 2: Pipeline health dashboard
