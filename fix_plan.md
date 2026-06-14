# Backend Fix Plan

## Scope

Static code review of the backend for:

- throughput bottlenecks for `~10,000` concurrent users
- growth to `~100,000` registered users
- auth/security risks
- database read/write hot spots
- cache design gaps
- queue/background-processing gaps

This is a code-based assessment. It does not include production query plans, APM traces, Redis hit ratios, or load-test data. The items below are still actionable because the current code has several structural problems that will fail well before the target traffic.

## Executive Summary

The current backend will not scale to the stated target in its present shape. The main blockers are:

1. synchronous SQLAlchemy sessions used inside async request handlers and async background loops
2. per-tick database inserts and commits for market data
3. serialized WebSocket tick processing guarded by one global lock
4. repeated database reads to rebuild cache on every live tick
5. no real queueing system; heavy jobs run inside the API process
6. public admin and graph pipeline endpoints with no authentication
7. weak session invalidation model and no rate limiting for auth
8. missing composite indexes on the largest filter paths

If traffic spikes, the likely failure mode is:

- DB pool exhaustion
- rising API latency due to blocking ORM work in the event loop
- Redis/DB churn from market data fanout
- duplicate WebSocket broadcasts
- request timeouts while graph jobs or table scans run

## Highest Priority Findings

### P0: API process is doing blocking DB work in async flows

Relevant code:

- `app/database.py:8-16`
- `app/main.py:74-118`
- `app/main.py:137-174`
- `app/api/v1/market_data.py:55-76`
- `app/api/v1/fno.py:72-195`

Problem:

- The app uses sync SQLAlchemy sessions/engine everywhere.
- Async endpoints and async background loops call sync DB queries directly.
- Under load, this blocks the event loop and collapses concurrency.

Impact:

- poor latency under moderate traffic
- WebSocket stalls
- background jobs interfering with request handling

Fix:

- move to SQLAlchemy async engine/session for request paths
- if migration must be staged, isolate sync ORM work in a threadpool as a temporary step
- use PgBouncer in transaction pooling mode
- tune pool sizes based on worker count and DB capacity, not a hardcoded `10/20`

### P0: Market-data ingestion is write-amplified and serialized

Relevant code:

- `app/main.py:81-105`
- `app/main.py:33-34`
- `app/services/market_data_service.py:288-377`
- `app/services/upstox_ws.py:130-235`

Problem:

- every incoming tick creates a DB row
- processing is serialized behind one global `_ws_tick_lock`
- option ticks are committed inside `process_option_tick`, and index ticks are committed in the caller
- `asyncio.create_task(self.on_tick(...))` is unbounded, so tasks can pile up faster than they drain
- one long-lived global DB session `_upstox_ws_db` is reused for the whole stream

Impact:

- throughput ceiling becomes "one tick at a time"
- memory growth from queued tasks and long-lived SQLAlchemy identity map
- DB write pressure becomes extreme during market hours

Fix:

- do not write every tick to PostgreSQL
- keep latest ticks in Redis only
- batch writes for historical persistence every `N` ticks or every `T` seconds
- replace the global lock with a bounded async queue and fixed worker pool
- use short-lived DB sessions per batch flush
- separate "real-time fanout" from "historical persistence"

### P0: Cache rebuild does DB reads on every live tick

Relevant code:

- `app/main.py:96-105`
- `app/services/market_data_service.py:407-438`
- `app/services/market_data_service.py:445-478`
- `app/services/market_data_service.py:280`

Problem:

- after each non-option tick, the code rebuilds index cache and sometimes queries the DB again
- `fetch_and_store_market_data()` deletes `market_data:*` with a Redis `SCAN` pattern delete
- `_get_cached_data()` and `rebuild_indices_cache()` do multiple `ORDER BY fetched_at DESC` queries per index

Impact:

- unnecessary DB reads during live traffic
- Redis keyspace scans during refresh
- high tail latency on market-data endpoints

Fix:

- maintain one Redis hash/object for the latest index snapshot
- update only the touched instrument in Redis
- publish that delta directly to WebSocket subscribers
- stop deleting cache by pattern on hot paths
- if historical rows remain in PostgreSQL, add a dedicated "latest snapshot" table instead of querying the append-only tick table

### P0: WebSocket broadcasting duplicates work and has lifecycle bugs

Relevant code:

- `app/services/ws_manager.py:57-76`
- `app/services/ws_manager.py:78-116`
- `app/main.py:218`

Problem:

- `broadcast()` sends to local sockets and also publishes to Redis
- `start_listener()` listens to the same Redis channel and sends again to the same sockets
- in a single-process deployment, clients can receive duplicate messages
- `ws_listener = asyncio.create_task(...)` is never stored in `WSManager._pubsub_task`
- `stop_listener()` therefore does not actually cancel the listener task

Impact:

- duplicate outbound traffic
- wasted CPU per message
- shutdown leaks / dangling listener task

Fix:

- choose one model:
  - local send only in single-process mode, or
  - publish once and let listeners fan out in multi-process mode
- store and manage the listener task correctly
- add backpressure and per-connection send timeouts

### P0: Sensitive and expensive admin operations are public

Relevant code:

- `app/api/v1/admin_monitor.py:14-227`
- `app/api/v1/graph.py:144-187`

Problem:

- admin monitor routes have no auth dependency
- graph pipeline run/reset/reprocess routes have no auth dependency
- graph admin mutation routes also have no auth dependency
- `/admin/tables/refresh` executes full table scans and metadata probes on demand

Impact:

- anyone can trigger heavy DB work
- anyone can run internal graph processing jobs
- high security and denial-of-service risk

Fix:

- add strict admin authentication and authorization
- remove public access to pipeline mutation endpoints
- disable or protect `/admin/tables/refresh`
- add audit logs for all admin operations

### P0: Auth/session model is weak for real-world usage

Relevant code:

- `app/dependencies/auth.py:18-92`
- `app/services/auth.py:88-116`
- `app/services/auth.py:186-217`
- `app/services/auth.py:268-278`

Problem:

- session validity depends on one boolean `is_logged_in`
- one login enables all outstanding access tokens for that user
- one logout invalidates all sessions for that user
- password reset does not revoke active sessions
- `get_current_user_optional()` does not enforce `type == access`
- every authenticated request hits the DB to load the user
- no refresh-token flow, no token versioning, no `jti`, no server-side revocation store
- no login/signup/password-reset rate limiting

Impact:

- poor security semantics
- poor multi-device behavior
- auth path adds DB load to every protected request

Fix:

- introduce access token `jti` + refresh tokens
- store refresh/session records server-side
- add `token_version` or per-session revocation
- revoke sessions on password reset, account deactivation, and suspicious login
- add rate limits by IP/email for auth endpoints
- consider caching validated session metadata in Redis

## Other Important Findings

### P1: Broker secrets are stored in plaintext and a default system broker is auto-seeded

Relevant code:

- `app/models/broker.py:19-41`
- `app/main.py:177-194`

Problem:

- broker `password`, `api_secret`, `access_token`, `refresh_token`, `otp` are stored plaintext
- startup seeds a default broker with `username="system"` and `password="system"`

Impact:

- severe secret-exposure risk
- lateral movement risk if DB is leaked

Fix:

- encrypt sensitive broker fields at rest
- remove plaintext broker password storage unless absolutely required
- remove auto-seeded default credentials from app startup
- load service credentials from secret manager or environment only

### P1: Startup path performs schema creation in the API process

Relevant code:

- `app/main.py:201-209`

Problem:

- `Base.metadata.create_all(bind=engine)` runs on application startup

Impact:

- schema drift risk
- startup stalls and metadata locks
- multiple app instances racing startup work

Fix:

- remove runtime `create_all`
- use Alembic migrations only

### P1: DB pool sizing is too small and static

Relevant code:

- `app/database.py:8-16`

Problem:

- `pool_size=10`, `max_overflow=20` is not aligned with 10k concurrent users
- there is no evidence of PgBouncer or worker-aware tuning

Impact:

- pool exhaustion
- request queuing and timeouts

Fix:

- introduce PgBouncer
- calculate app pool sizes per worker/process
- instrument connection wait time and saturation

### P1: F&O option-chain path can trigger expensive fallbacks per request

Relevant code:

- `app/api/v1/fno.py:72-195`
- `app/api/v1/fno.py:214-241`

Problem:

- cache miss leads to DB reads plus Redis reads plus optional Upstox REST fallback
- low live-price coverage triggers upstream REST calls per request
- `/fno/subscribe` is public and can keep adding option keys to one global WS subscription set with no eviction

Impact:

- upstream API amplification
- memory growth in `_subscribed_option_keys`
- one user can expand system load for all users

Fix:

- require auth for subscription endpoints
- maintain per-client subscription accounting with TTL and unsubscribe on disconnect
- precompute/cache hot option chains by symbol+expiry
- cap option-chain size and add request throttling

### P1: Waitlist signup has race conditions

Relevant code:

- `app/api/v1/waitlist.py:18-70`

Problem:

- `max(queue_position) + 1` is not concurrency-safe
- referral code uniqueness is checked in a loop before insert
- there is no retry-on-unique-violation logic

Impact:

- duplicate queue positions under concurrent signups
- transaction retries will surface as 500s

Fix:

- use a DB sequence or generated rank source
- rely on DB uniqueness constraints and retry on conflict
- do referrer increment and entry insert in one transaction

### P1: Graph endpoints and pipeline will become DB hot spots

Relevant code:

- `app/components/graph/pipeline.py:47-90`
- `app/components/graph/pipeline.py:173-190`
- `app/components/graph/graph_engine.py:38-97`
- `app/components/graph/graph_engine.py:237-309`
- `app/services/graph_service.py:123-207`
- `app/api/v1/graph.py:57-88`

Problem:

- graph pipeline runs inside the API process every 120s
- graph traversal does N+1 queries per entity/relationship expansion
- relationship building does pairwise work per extraction and per-pair lookup/upsert
- merge operations loop through many row-level queries

Impact:

- CPU and DB contention with user-facing requests
- graph routes degrade sharply as graph size grows

Fix:

- move graph pipeline to a separate worker service
- batch relationship upserts
- prefetch entity/edge sets per traversal level
- cache graph summary/top influencer outputs
- add indexes listed below

### P1: Logging path is too chatty and synchronous for high traffic

Relevant code:

- `app/main.py:310-339`
- `app/utils/logger.py:129-166`
- `app/services/email.py:10-25`

Problem:

- every request logs at `INFO`
- logs are written to console plus two rotating files synchronously
- email logs include recipient metadata

Impact:

- disk I/O and CPU overhead at traffic peaks
- log volume grows faster than needed
- avoidable PII exposure in logs

Fix:

- reduce request logging to sampled/access-log style
- move structured logs to stdout and let infrastructure handle shipping
- scrub email and credential-related fields

## Database Problems and Index Plan

### Current model issues

Relevant code:

- `app/models/market_data.py:12-50`
- `app/models/fno.py:39-99`
- `app/models/news.py:8-47`
- `app/models/graph.py:9-143`

Problems:

- `market_data` only has an index on `instrument_key`, but hot queries use `instrument_key + fetched_at desc`
- graph tables have almost no indexes on the columns used in filters/joins
- `news_extraction.news_id` is not indexed
- `fno_expiries(symbol_id, expiry_timestamp)` should be indexed or unique
- `market_timings(timing_date, exchange)` should be indexed or unique
- `market_holidays(holiday_date)` may need uniqueness depending on intended cardinality

### Recommended indexes

Add migrations for at least:

```sql
CREATE INDEX CONCURRENTLY idx_market_data_instrument_fetched_desc
ON market_data (instrument_key, fetched_at DESC);

CREATE INDEX CONCURRENTLY idx_market_status_exchange_checked_desc
ON market_status (exchange, last_checked_at DESC);

CREATE UNIQUE INDEX CONCURRENTLY uq_market_timings_date_exchange
ON market_timings (timing_date, exchange);

CREATE INDEX CONCURRENTLY idx_news_article_published_at
ON market_news (published_at DESC);

CREATE INDEX CONCURRENTLY idx_news_article_source_published
ON market_news (source_name, published_at DESC);

CREATE INDEX CONCURRENTLY idx_news_article_author_published
ON market_news (author, published_at DESC);

CREATE INDEX CONCURRENTLY idx_news_extraction_news_id
ON news_extraction (news_id);

CREATE UNIQUE INDEX CONCURRENTLY uq_fno_expiries_symbol_expiry
ON fno_expiries (symbol_id, expiry_timestamp);

CREATE INDEX CONCURRENTLY idx_fno_instruments_expiry_underlying_type_active_strike
ON fno_instruments (expiry_id, underlying_symbol, instrument_type, is_active, strike_price);

CREATE INDEX CONCURRENTLY idx_entity_resolution_log_extraction
ON nse_entity_resolution_log (extraction_id);

CREATE INDEX CONCURRENTLY idx_entity_resolution_log_resolved
ON nse_entity_resolution_log (resolved_id);

CREATE INDEX CONCURRENTLY idx_graph_event_extraction
ON nse_events (extraction_id);

CREATE INDEX CONCURRENTLY idx_graph_event_news
ON nse_events (news_id);

CREATE INDEX CONCURRENTLY idx_relationship_source
ON nse_relationships (source_entity);

CREATE INDEX CONCURRENTLY idx_relationship_target
ON nse_relationships (target_entity);

CREATE INDEX CONCURRENTLY idx_relationship_pair
ON nse_relationships (source_entity, target_entity);

CREATE INDEX CONCURRENTLY idx_relationship_evidence_relationship
ON nse_relationship_evidence (relationship_id);

CREATE INDEX CONCURRENTLY idx_propagation_source_target
ON nse_propagation_scores (source_id, target_id);
```

### Data model changes

- split market data into:
  - `market_data_latest` for current snapshot
  - `market_data_history` for batched historical persistence
- partition `market_data_history` by day/week if historical retention is required
- define retention policy for raw ticks
- normalize auth/session storage instead of overloading `users.is_logged_in`

## Cache Plan

### Current cache problems

- cache is mostly a passive lookup layer, not the source of truth for hot real-time state
- hot endpoints still fall back to DB frequently
- cache invalidation uses pattern deletion on hot path
- there is no negative-cache or stale-while-revalidate pattern

### Target cache design

1. Redis becomes the primary read path for hot market data.
2. PostgreSQL becomes the durable store, not the live fanout store.
3. Keep these Redis keys:
   - `market:indices:latest`
   - `market:status:latest`
   - `market:option:{instrument_key}`
   - `market:option_chain:{symbol}:{expiry}`
4. Publish only deltas over pub/sub or a stream.
5. Add versioned cache keys for option-chain snapshots.
6. Add metrics:
   - hit ratio
   - rebuild count
   - average payload size
   - publish latency

## Queueing Plan

### Current gap

- no real queueing system exists
- FastAPI `BackgroundTasks` is used for email
- graph pipeline runs inside API lifespan
- market tick processing is effectively an in-process queue with no bounds or observability

### Required queueing design

Introduce a real worker system. Acceptable options:

- Celery + Redis
- Dramatiq + Redis
- RQ + Redis

Recommended job classes:

1. `send_verification_email`
2. `send_password_reset_email`
3. `persist_market_tick_batch`
4. `build_option_chain_snapshot`
5. `graph_incremental_run`
6. `graph_full_run`
7. `refresh_table_metadata`

Requirements:

- bounded retries
- dead-letter handling
- idempotency keys
- job timeouts
- worker concurrency separate from API concurrency

## Auth Hardening Plan

### Immediate

1. Protect admin and graph mutation endpoints.
2. Add rate limiting to:
   - `/api/v1/auth/login`
   - `/api/v1/auth/signup`
   - `/api/v1/auth/forgot-password`
   - `/api/v1/auth/resend-verification`
3. Enforce token type in optional auth dependency.
4. Revoke sessions on password reset.
5. Remove default seeded broker credentials.

### Next

1. Add refresh tokens with server-side session records.
2. Add `jti` to access tokens.
3. Add `token_version` or per-session revocation.
4. Cache session metadata in Redis.
5. Add suspicious-login and lockout policy.

## Phased Execution Plan

### Phase 0: Containment

Target: stop the worst security and load risks this week.

1. Protect `/admin/*` and graph pipeline/admin routes.
2. Remove `Base.metadata.create_all()` from startup.
3. Remove default seeded broker password/token behavior.
4. Add auth rate limiting.
5. Disable or heavily restrict `/admin/tables/refresh`.
6. Stop duplicate WebSocket broadcast behavior.

### Phase 1: Real-time Path Rewrite

Target: make market-data traffic survivable.

1. Replace per-tick DB writes with Redis-first updates.
2. Add bounded ingestion queue and worker batch flush.
3. Remove global tick lock.
4. Replace long-lived `_upstox_ws_db` session with short-lived batch sessions.
5. Store latest index snapshot directly in Redis without DB round-trips.
6. Add per-client option subscription lifecycle and caps.

### Phase 2: DB and Index Work

Target: reduce query cost and contention.

1. Add composite indexes listed above.
2. Introduce `market_data_latest` table.
3. Partition or retain-prune historical tick data.
4. Add uniqueness and transactional fixes to waitlist path.
5. Review query plans for graph and news endpoints.

### Phase 3: Background Architecture

Target: remove heavy jobs from the API process.

1. Move graph pipeline to worker service.
2. Move email sending to job queue.
3. Move table metadata refresh to scheduled worker.
4. Add job metrics and dashboards.

### Phase 4: Auth and Session Redesign

Target: make auth safe and cheap under load.

1. Add refresh/session table.
2. Add token revocation model.
3. Cache active session/user flags in Redis.
4. Add audit logging and anomaly detection.

### Phase 5: Load Validation

Target: prove the fixes.

1. Run k6/Locust scenarios for:
   - 10k concurrent reads on market endpoints
   - login burst tests
   - option-chain fanout
   - WebSocket subscription churn
2. Capture:
   - p50/p95/p99 latency
   - DB connection wait
   - Redis ops/sec
   - WS outbound queue depth
   - worker lag

## Suggested Success Criteria

- market-data read endpoints serve from Redis with minimal DB usage
- no per-tick synchronous DB commits in request-serving process
- admin/pipeline mutation routes require admin auth
- all auth endpoints are rate limited
- protected-request auth path does not require a full DB fetch on every call
- graph jobs run outside API workers
- DB indexes exist for all dominant filters and orderings
- 10k concurrent market-data consumers do not exhaust DB pool

## Recommended First 10 Changes

1. Add admin auth to `admin_monitor.py`.
2. Add admin auth to graph pipeline/admin routes.
3. Remove `create_all()` from startup.
4. Remove default broker seeding with plaintext credentials.
5. Fix WS double-broadcast and listener task management.
6. Replace per-tick DB commit path with bounded queue.
7. Stop rebuilding indices from DB on every tick.
8. Add composite indexes for `market_data`, graph tables, and `news_extraction`.
9. Add rate limiting and token-type enforcement in auth dependencies.
10. Move email and graph work to a real worker queue.

## Notes

The biggest architectural mistake in the current codebase is treating PostgreSQL as both:

- the real-time state store
- the historical event store
- the auth/session validation store
- the analytics/graph job store

for the same API process, at the same time.

That is why the fixes above focus first on separation of concerns:

- Redis for hot state
- PostgreSQL for durable data
- worker queue for heavy/background jobs
- API workers for request handling only
