from collections import deque
from typing import Any, Callable

import redis
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.graph import CanonicalEntity, GraphMetric, PropagationScore, Relationship
from app.utils.logger import get_logger

logger = get_logger(__name__)

_settings = get_settings()

_REDIS_CURSOR_KEY = "graph:propagation:last_entity_id"


class PropagationEngine:
    def __init__(self, db_session_factory: Callable[[], Session]):
        self._session_factory = db_session_factory

    def get_session(self) -> Session:
        return self._session_factory()

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

    def compute_propagation(
        self, entity_id: int, max_depth: int = 3, decay: float = 0.5
    ) -> list[PropagationScore]:
        session = self.get_session()
        try:
            paths = self._bfs_traverse(entity_id, max_depth, decay, session)

            score_map: dict[tuple[int, int], dict[str, Any]] = {}
            for path_info in paths:
                path = path_info["path"]
                hops = path_info["hops"]
                target_id = path[-1]

                if target_id == entity_id:
                    continue

                score = path_info["score"]

                if score <= 0.01:
                    continue

                key = (entity_id, target_id)
                if key not in score_map or score > score_map[key]["score"]:
                    score_map[key] = {
                        "path": [str(eid) for eid in path],
                        "hops": hops,
                        "score": score,
                    }

            target_ids = [t for (_, t) in score_map.keys()]
            existing = (
                session.query(PropagationScore)
                .filter(
                    PropagationScore.source_id == entity_id,
                    PropagationScore.target_id.in_(target_ids),
                )
                .all()
            )
            existing_map: dict[tuple[int, int], PropagationScore] = {}
            for record in existing:
                existing_map[(record.source_id, record.target_id)] = record

            created: list[PropagationScore] = []
            for (source_id, target_id), info in score_map.items():
                if (source_id, target_id) in existing_map:
                    existing_record = existing_map[(source_id, target_id)]
                    if info["score"] > (existing_record.propagation_score or 0):
                        existing_record.propagation_score = info["score"]
                        existing_record.influence_path = info["path"]
                        existing_record.hop_count = info["hops"]
                        existing_record.decay_factor = decay
                        existing_record.computed_at = func.now()
                        created.append(existing_record)
                else:
                    record = PropagationScore(
                        source_id=source_id,
                        target_id=target_id,
                        propagation_score=info["score"],
                        influence_path=info["path"],
                        hop_count=info["hops"],
                        decay_factor=decay,
                    )
                    session.add(record)
                    created.append(record)

            session.commit()
            logger.info(
                "Computed propagation for entity %s: %s paths created/updated",
                entity_id,
                len(created),
            )
            return created
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _bfs_traverse(
        self, start_id: int, max_depth: int, decay: float, db_session: Session
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        queue: deque[tuple[int, list[int], float, int]] = deque()
        queue.append((start_id, [start_id], 1.0, 0))

        while queue:
            current_id, path, cum_weight, hops = queue.popleft()

            if hops > 0:
                score = cum_weight * (decay ** (hops - 1))
                results.append({
                    "path": list(path),
                    "score": score,
                    "hops": hops,
                })

            if hops >= max_depth:
                continue

            relationships = self._get_relationships_for_entity(current_id, db_session)

            for rel in relationships:
                if rel.source_entity == current_id:
                    neighbor_id = rel.target_entity
                else:
                    neighbor_id = rel.source_entity

                if neighbor_id in path:
                    continue

                weight = rel.weight or 1.0
                new_cum_weight = cum_weight * weight

                new_path = path + [neighbor_id]
                queue.append((neighbor_id, new_path, new_cum_weight, hops + 1))

        return results

    def _get_relationships_for_entity(
        self, entity_id: int, db_session: Session
    ) -> list[Relationship]:
        return (
            db_session.query(Relationship)
            .filter(
                (Relationship.source_entity == entity_id)
                | (Relationship.target_entity == entity_id)
            )
            .all()
        )

    def compute_all_propagation(
        self, top_n: int = 100, max_depth: int = 3, decay: float = 0.5
    ) -> dict[str, int]:
        stats: dict[str, int] = {"processed": 0, "scores_created": 0, "errors": 0}

        r = self._get_redis()
        last_entity_id = 0
        if r is not None:
            try:
                val = r.get(_REDIS_CURSOR_KEY)
                if val is not None:
                    last_entity_id = int(val)
            except Exception as e:
                logger.warning("Failed to read Redis cursor: %s", e)

        session = self.get_session()
        try:
            entities = (
                session.query(GraphMetric.entity_id)
                .filter(GraphMetric.entity_id > last_entity_id)
                .order_by(GraphMetric.pagerank.desc())
                .limit(top_n)
                .all()
            )

            for (entity_id,) in entities:
                try:
                    scores = self.compute_propagation(entity_id, max_depth, decay)
                    stats["processed"] += 1
                    stats["scores_created"] += len(scores)
                except Exception as e:
                    logger.error(
                        "Failed to compute propagation for entity %s: %s",
                        entity_id,
                        e,
                    )
                    stats["errors"] += 1

                last_entity_id = entity_id

            if r is not None:
                try:
                    r.set(_REDIS_CURSOR_KEY, last_entity_id)
                except Exception as e:
                    logger.warning("Failed to update Redis cursor: %s", e)

            logger.info(
                "compute_all_propagation complete — processed=%s, scores=%s, errors=%s",
                stats["processed"],
                stats["scores_created"],
                stats["errors"],
            )
            return stats
        finally:
            session.close()
            if r is not None:
                try:
                    r.close()
                except Exception:
                    pass

    def get_influence_path(self, source_id: int, target_id: int) -> dict | None:
        session = self.get_session()
        try:
            record = (
                session.query(PropagationScore)
                .filter(
                    PropagationScore.source_id == source_id,
                    PropagationScore.target_id == target_id,
                )
                .first()
            )
            if record is None:
                return None

            path_ints = [int(eid) for eid in (record.influence_path or [])]
            return {
                "source_id": record.source_id,
                "target_id": record.target_id,
                "path": path_ints,
                "score": record.propagation_score,
                "hops": record.hop_count,
            }
        finally:
            session.close()

    def get_top_influencers(self, limit: int = 20) -> list[dict]:
        session = self.get_session()
        try:
            rows = (
                session.query(
                    PropagationScore.source_id,
                    func.sum(PropagationScore.propagation_score).label("total_influence"),
                )
                .group_by(PropagationScore.source_id)
                .order_by(func.sum(PropagationScore.propagation_score).desc())
                .limit(limit)
                .all()
            )

            entity_ids = [row.source_id for row in rows]
            entities = (
                session.query(CanonicalEntity.id, CanonicalEntity.canonical_name)
                .filter(CanonicalEntity.id.in_(entity_ids))
                .all()
            )
            entity_name_map = {e.id: e.canonical_name for e in entities}

            results = []
            for row in rows:
                results.append({
                    "entity_id": row.source_id,
                    "entity_name": entity_name_map.get(row.source_id, "Unknown"),
                    "total_influence": float(row.total_influence),
                })
            return results
        finally:
            session.close()
