# Portal Backend

FastAPI backend for [arinedge.com](https://arinedge.com) — the core API gateway serving the Angular frontend, admin panel, and external clients. Handles authentication, broker integration, real-time market data (Upstox WebSocket), F&O analytics, news, graph intelligence, and service monitoring.

## Architecture

```
┌──────────────┐  ┌────────────────┐  ┌─────────────┐
│  Angular SPA  │  │  Admin Panel   │  │  External   │
│  :4200/3000   │  │  :4201         │  │  Clients    │
└──────┬───────┘  └───────┬────────┘  └──────┬──────┘
       │                  │                   │
       └──────────────────┼───────────────────┘
                          │
               ┌──────────▼──────────┐
               │   FastAPI Gateway   │
               │  data.arinedge.com  │
               │  :8000              │
               └──────┬──────┬───────┘
                      │      │
            ┌─────────▼┐  ┌──▼────────┐
            │PostgreSQL│  │   Redis   │
            │:5432     │  │  :6379    │
            └──────────┘  └───────────┘
```

- **Auth** — JWT-based signup/login, email verification via Zavu, password reset
- **Market Data** — Live index/option ticks via Upstox WebSocket, cached in Redis, broadcast via internal WebSocket
- **F&O** — Option chain, expiry management, Greeks, GEX, max pain via Upstox REST API
- **Broker Management** — Multi-broker CRUD (Upstox), token management
- **News** — Paginated news articles with source/author/date filters from `market_news` table
- **Graph Intelligence** — Entity resolution, canonical entities, relationships, events, metrics (NetworkX + LLM)
- **Waitlist** — Referral-based waitlist with queue positions and bonus system
- **Service Monitor** — Admin dashboard for tracking all microservice health, run history, table metadata
- **Sitemap** — Dynamic XML sitemap generation for SEO

## Tech Stack

- **Framework:** FastAPI + Uvicorn
- **Database:** PostgreSQL 16 (SQLAlchemy ORM + Alembic migrations)
- **Cache:** Redis 7 (market data, session caching)
- **Data Sources:** Upstox REST API + WebSocket (live market), yfinance (historical)
- **LLM:** Groq (Llama 3.3 70B) + OpenRouter (DeepSeek) for graph extraction pipeline
- **Email:** Zavu API
- **Infrastructure:** Docker, single-container deployment behind nginx

## Data Sources

| Source | Data | Access |
|---|---|---|
| Upstox REST API | F&O symbols, expiries, option chains, Greeks, GEX, max pain, live indices | Broker access token (REST + WS) |
| Upstox WebSocket | Real-time index/option ticks (NSE_FO, BSE_FO, NSE_INDEX) | Broker access token |
| PostgreSQL | Cached market data, user profiles, news, entities, waitlist, service runs | Direct ORM |
| Redis | Market data snapshots, uptime, cache layer | Internal |
| yfinance | Historical stock data (fallsback when Upstox unavailable) | Public API |
| Groq / OpenRouter | LLM extraction pipeline for graph intelligence | API keys |

## Endpoints

All endpoints under `https://data.arinedge.com/api/v1/`

### Authentication (`/auth`)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/signup` | Create account |
| `POST` | `/auth/login` | Login, returns JWT |
| `POST` | `/auth/verify-email` | Verify email with token |
| `POST` | `/auth/resend-verification` | Resend verification email |
| `POST` | `/auth/forgot-password` | Request password reset |
| `POST` | `/auth/reset-password` | Reset password with token |

### Users (`/users`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/users/me` | Current user profile |
| `PUT` | `/users/me` | Update profile |
| `DELETE` | `/users/me` | Deactivate account |

### Brokers (`/brokers`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/brokers/` | List user's brokers |
| `POST` | `/brokers/` | Add broker account |
| `GET` | `/brokers/{id}` | Get broker details |
| `PUT` | `/brokers/{id}` | Update broker |
| `DELETE` | `/brokers/{id}` | Remove broker |

### Market Data (`/market`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/market/data` | Latest market snapshot (indices, status) |
| `WS` | `/market/ws` | Real-time market data WebSocket |

### F&O (`/fno`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/fno/symbols` | List F&O symbols (searchable, filterable) |
| `GET` | `/fno/symbols/{symbol}/expiries` | Available expiries for a symbol |
| `GET` | `/fno/option-chain` | Full option chain (strikes, OI, volume, IV, Greeks) |
| `GET` | `/fno/option-chain/geeks` | Greeks-only view for all strikes |
| `GET` | `/fno/option-chain/gex` | GEX profile across strikes |
| `GET` | `/fno/option-chain/max-pain` | Max pain strike calculation |

### News (`/news`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/news` | Paginated news articles with filters |
| `GET` | `/news/filters` | Available filter options (sources, authors, dates) |
| `GET` | `/news/{id}` | Single article detail |
| `GET` | `/news/{id}/extractions` | LLM extractions for an article |

### Graph Intelligence (`/graph`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/graph/entities` | Search canonical entities |
| `GET` | `/graph/entities/{id}` | Entity detail with relationships |
| `PUT` | `/graph/entities/{id}` | Update entity metadata |
| `DELETE` | `/graph/entities/{id}` | Remove entity |
| `GET` | `/graph/entities/{id}/relationships` | Entity's relationships |
| `GET` | `/graph/entities/{id}/events` | Entity's event timeline |
| `POST` | `/graph/entities/merge` | Merge duplicate entities |
| `GET` | `/graph/relationships` | List relationships (filterable) |
| `PUT` | `/graph/relationships/{id}` | Override relationship type |
| `DELETE` | `/graph/relationships/{id}` | Remove relationship |
| `GET` | `/graph/events` | List graph events |
| `GET` | `/graph/metrics` | Graph stats (nodes, edges, types, sectors) |
| `GET` | `/graph/data` | Full graph data dump for visualization |

### Waitlist (`/waitlist`)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/waitlist` | Join waitlist (with referral) |
| `GET` | `/waitlist/stats/{email}` | Referral stats and queue position |

### Admin Monitor (`/admin`)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/admin/services` | All registered services + latest run |
| `GET` | `/admin/services/{name}` | Service detail |
| `GET` | `/admin/services/{name}/runs` | Run history for a service |
| `POST` | `/admin/services/{name}/runs` | Register a new run |
| `POST` | `/admin/services` | Register a new service |
| `PUT` | `/admin/services/{name}` | Update service config |
| `DELETE` | `/admin/services/{name}` | Unregister service |
| `GET` | `/admin/tables` | Table metadata (row counts, sizes) |

### Sitemap

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/sitemap.xml` | Dynamic XML sitemap |

### System

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |

## Background Tasks

| Task | Description | Schedule |
|---|---|---|
| Market Data Poller | Checks market open/close, starts/stops Upstox WebSocket accordingly | Every 60s |
| Graph Pipeline | LLM entity extraction pipeline, processes unprocessed articles via Groq/OpenRouter | Every 120s |

## Database (45+ tables)

Major model groups:
- **Auth:** `users`, `email_verification_tokens`, `password_reset_tokens`
- **Market Data:** `stock_indices`, `index_data`, `option_chain_cache`
- **F&O:** `fno_symbols`, `fno_expiries`
- **News:** `market_news`, `news_extraction`
- **Graph:** `canonical_entities`, `entity_aliases`, `relationships`, `graph_events`, `graph_metrics`
- **Brokers:** `brokers`
- **Monitor:** `service_registry`, `service_runs`, `table_metadata`
- **Waitlist:** `waitlist_entries`
- **Backfill:** `nse_securities`, `bulk_price_sync_log`

## Scheduled Jobs

Market data poller checks market status every 60s. Graph pipeline runs every 120s. All data syncs (market data sync, bulk price sync) run from the research/services/market_data_sync service (separate container).

## Key Design Decisions

- **Upstox WebSocket lifecycle** — auto-started on market open, stopped on close; handles reconnect gracefully
- **Redis cache** — market data snapshots cached with 60s TTL; enables fast recovery on restart
- **Option chain** — cached in DB after fetch; Upstox API is polled only on expiry or explicit refresh
- **Graph pipeline** — processes news extractions from `research/services/kiyannet`, resolves entities canonically, builds relationship graph
- **Correlation IDs** — every request gets a `X-Correlation-ID` header; logged to JSON for debugging
- **Global exception handler** — catches unhandled errors, returns correlation ID for debugging

## Deployment

```bash
# Deploy with main docker-compose (from project root)
docker compose up -d --build

# The API runs as: arinedge_backend
# Port: 8000
# Auto-restarts via: restart: unless-stopped
```

## Project Structure

```
backend/
├── app/
│   ├── main.py                 # FastAPI entry, lifespan, CORS, middleware
│   ├── config.py               # Settings from .env (pydantic-settings)
│   ├── database.py             # SQLAlchemy engine, session, Base
│   ├── api/v1/                 # Route handlers
│   │   ├── auth.py             # Auth endpoints
│   │   ├── users.py            # User CRUD
│   │   ├── brokers.py          # Broker management
│   │   ├── market_data.py      # Market data + WebSocket
│   │   ├── fno.py              # F&O option chain, Greeks, GEX
│   │   ├── news.py             # News articles
│   │   ├── graph.py            # Graph intelligence
│   │   ├── waitlist.py         # Referral waitlist
│   │   ├── admin_monitor.py    # Service monitoring dashboard
│   │   └── sitemap.py          # Dynamic sitemap
│   ├── models/                 # SQLAlchemy models (all 45+ tables)
│   ├── schemas/                # Pydantic request/response schemas
│   ├── services/               # Business logic
│   │   ├── market_data_service.py
│   │   ├── broker_service.py
│   │   ├── fno_service.py
│   │   ├── news_service.py
│   │   ├── graph_service.py
│   │   ├── upstox.py           # Upstox REST client
│   │   ├── upstox_ws.py        # Upstox WebSocket client
│   │   └── ws_manager.py       # Internal WS broadcast
│   ├── components/graph/       # Graph pipeline components
│   ├── dependencies/           # JWT deps, auth guards
│   └── utils/                  # Security, logging, Redis cache
├── alembic/                    # DB migrations
├── logs/                       # JSON + plain log files
├── seed.py                     # Test user seed
├── Dockerfile
├── requirements.txt
└── .env.example
```
