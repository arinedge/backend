import asyncio

import redis
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.graph import CanonicalEntity, GraphEvent, Relationship
from app.utils.logger import get_logger

from .analytics import GraphAnalytics
from .entity_resolver import EntityResolver
from .event_normalizer import EventNormalizer
from .graph_engine import GraphEngine
from .propagation_engine import PropagationEngine

logger = get_logger(__name__)
_settings = get_settings()


class GraphPipeline:
    def __init__(self):
        self.resolver = EntityResolver(SessionLocal)
        self.normalizer = EventNormalizer(SessionLocal)
        self.graph_engine = GraphEngine(SessionLocal)
        self.propagation = PropagationEngine(SessionLocal)
        self.analytics = GraphAnalytics(SessionLocal)

    def _sync_cursor(self, source_key: str, target_key: str) -> None:
        r = self._get_redis()
        if r is None:
            return
        try:
            source_val = r.get(source_key)
            if source_val is not None:
                target_val = r.get(target_key)
                if target_val is None or int(source_val) > int(target_val):
                    r.set(target_key, source_val)
        except Exception as e:
            logger.warning("Failed to sync cursor %s → %s: %s", source_key, target_key, e)
        finally:
            try:
                r.close()
            except Exception:
                pass

    def run_incremental(self) -> dict:
        logger.info("Pipeline: starting incremental run")

        resolve_stats = self.resolver.bulk_resolve_all(batch_size=50)
        self._sync_cursor(
            "graph:resolver:last_extraction_id",
            "graph:normalizer:last_extraction_id",
        )

        normalize_stats = self.normalizer.normalize_batch(limit=50)
        self._sync_cursor(
            "graph:normalizer:last_extraction_id",
            "graph:engine:last_extraction_id",
        )

        graph_stats = self.graph_engine.run_full_graph_build(batch_size=50)

        self._record_last_run("incremental")

        combined = {
            "phase": "incremental",
            "resolver": resolve_stats,
            "normalizer": normalize_stats,
            "graph_engine": graph_stats,
        }
        logger.info("Pipeline: incremental run complete — %s", combined)
        return combined

    def run_full(self) -> dict:
        logger.info("Pipeline: starting full run")
        analytics_stats = self.analytics.compute_all_metrics()
        full_analytics_stats = self.analytics.run_full_analytics()
        propagation_stats = self.propagation.compute_all_propagation()

        self._record_last_run("full")

        combined = {
            "phase": "full",
            "analytics": analytics_stats,
            "full_analytics": full_analytics_stats,
            "propagation": propagation_stats,
        }
        logger.info("Pipeline: full run complete — %s", combined)
        return combined

    def run_single_extraction(self, extraction_id: int) -> dict:
        logger.info("Pipeline: starting single extraction run for %s", extraction_id)
        resolve_logs = self.resolver.resolve_extraction_names(extraction_id)
        events = self.normalizer.normalize_extraction_events(extraction_id)
        relationships = self.graph_engine.build_relationships_for_extraction(extraction_id)

        stats = {
            "extraction_id": extraction_id,
            "entities_resolved": len(resolve_logs),
            "events_normalized": len(events),
            "relationships_built": len(relationships),
        }
        logger.info("Pipeline: single extraction run complete — %s", stats)
        return stats

    def get_pipeline_status(self) -> dict:
        session: Session = SessionLocal()
        try:
            total_entities = session.query(CanonicalEntity).count()
            total_events = session.query(GraphEvent).count()
            total_relationships = session.query(Relationship).count()
        finally:
            session.close()

        r = self._get_redis()
        last_incremental = None
        last_full = None
        if r is not None:
            try:
                last_incremental = r.get(self._redis_key("last_run:incremental"))
                last_full = r.get(self._redis_key("last_run:full"))
            except Exception as e:
                logger.warning("Failed to read pipeline timestamps from Redis: %s", e)
            finally:
                try:
                    r.close()
                except Exception:
                    pass

        return {
            "total_resolved_entities": total_entities,
            "total_events_normalized": total_events,
            "total_relationships_built": total_relationships,
            "last_incremental_run": last_incremental,
            "last_full_run": last_full,
        }

    def _record_last_run(self, phase: str) -> None:
        r = self._get_redis()
        if r is not None:
            try:
                from datetime import datetime, timezone

                r.set(self._redis_key(f"last_run:{phase}"), datetime.now(timezone.utc).isoformat())
            except Exception as e:
                logger.warning("Failed to record last run timestamp in Redis: %s", e)
            finally:
                try:
                    r.close()
                except Exception:
                    pass

    def _get_redis(self) -> redis.Redis | None:
        try:
            return redis.Redis(
                host=_settings.REDIS_HOST,
                port=_settings.REDIS_PORT,
                password=_settings.REDIS_PASSWORD or None,
                db=_settings.REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
        except Exception as e:
            logger.warning("Failed to connect to Redis: %s", e)
            return None

    @staticmethod
    def _redis_key(key: str) -> str:
        return f"graph:pipeline:{key}"

    async def run_pipeline_loop(
        self, interval_seconds: int = 120, initial_delay_seconds: int = 0
    ) -> None:
        logger.info(
            "Pipeline loop started (interval=%ss, initial_delay=%ss)",
            interval_seconds,
            initial_delay_seconds,
        )
        if initial_delay_seconds > 0:
            logger.info("Pipeline: waiting %ss before first run", initial_delay_seconds)
            await asyncio.sleep(initial_delay_seconds)
        while True:
            try:
                stats = self.run_incremental()
                logger.info("Pipeline cycle complete — %s", stats)
            except Exception as e:
                logger.error("Pipeline cycle failed: %s", e, exc_info=True)
            await asyncio.sleep(interval_seconds)

    def reset_cursors(self) -> dict:
        r = self._get_redis()
        if r is None:
            return {"status": "error", "message": "Redis not available"}
        keys = [
            "graph:resolver:last_extraction_id",
            "graph:normalizer:last_extraction_id",
            "graph:engine:last_extraction_id",
        ]
        deleted = 0
        for key in keys:
            try:
                r.delete(key)
                deleted += 1
            except Exception as e:
                logger.warning("Failed to delete cursor %s: %s", key, e)
        try:
            r.close()
        except Exception:
            pass
        logger.info("Pipeline cursors reset: %s keys deleted", deleted)
        return {"status": "ok", "cursors_deleted": deleted}

    async def run_full_pipeline_async(self) -> dict:
        logger.info("Pipeline: running full pipeline async")
        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(None, self.run_full)
        logger.info("Pipeline: full pipeline async complete — %s", stats)
        return stats
