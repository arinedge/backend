from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

import redis
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.graph import (
    CanonicalEntity,
    EntityResolutionLog,
    GraphEvent,
    Relationship,
    RelationshipEvidence,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_settings = get_settings()

_REDIS_CURSOR_KEY = "graph:engine:last_extraction_id"

_ACQUISITION_KEYWORDS = {"acqui", "merger", "takeover", "buyout", "acquisition"}
_INVESTMENT_KEYWORDS = {"invest", "funding", "series", "raised", "seed", "round"}
_PARTNERSHIP_KEYWORDS = {"partner", "collaborat", "alliance", "joint venture"}
_COMPETITOR_KEYWORDS = {"compet", "rival", "lawsuit", "dispute", "litigation"}


class GraphEngine:
    def __init__(self, db_session_factory: Callable[[], Session]):
        self._session_factory = db_session_factory

    def get_session(self) -> Session:
        return self._session_factory()

    def build_relationships_for_extraction(self, extraction_id: int) -> list[Relationship]:
        session = self.get_session()
        try:
            entity_ids = self._get_entities_for_extraction(extraction_id, session)
            events = self._get_events_for_extraction(extraction_id, session)

            if len(entity_ids) < 2:
                logger.debug("Extraction %s has < 2 entities, skipping", extraction_id)
                return []

            entities = (
                session.query(CanonicalEntity)
                .filter(CanonicalEntity.id.in_(entity_ids))
                .all()
            )
            entity_map = {e.id: e for e in entities}

            relationships: list[Relationship] = []

            for i in range(len(entity_ids)):
                for j in range(i + 1, len(entity_ids)):
                    source_id = entity_ids[i]
                    target_id = entity_ids[j]

                    source_entity = entity_map.get(source_id)
                    target_entity = entity_map.get(target_id)

                    relation_type = self._get_co_occurrence_type(source_entity, target_entity)

                    event_hint = self._extract_relation_from_events(source_id, events)
                    if event_hint:
                        relation_type = event_hint

                    news_id = events[0].news_id if events else None
                    evidence_span = events[0].evidence_span if events else None
                    confidence = max(
                        (e.confidence or 0.5) for e in events
                    ) if events else 0.5

                    evidence = {
                        "extraction_id": extraction_id,
                        "news_id": news_id,
                        "evidence_span": evidence_span,
                        "confidence": confidence,
                    }

                    rel = self._upsert_relationship(
                        source_id, target_id, relation_type, evidence, session
                    )
                    relationships.append(rel)

            session.commit()

            logger.info(
                "Built %s relationships for extraction %s",
                len(relationships),
                extraction_id,
            )

            return relationships
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _get_entities_for_extraction(
        self, extraction_id: int, db_session: Session
    ) -> list[int]:
        rows = (
            db_session.query(EntityResolutionLog.resolved_id)
            .filter(EntityResolutionLog.extraction_id == extraction_id)
            .distinct()
            .all()
        )
        return [row[0] for row in rows]

    def _get_events_for_extraction(
        self, extraction_id: int, db_session: Session
    ) -> list[GraphEvent]:
        return (
            db_session.query(GraphEvent)
            .filter(GraphEvent.extraction_id == extraction_id)
            .all()
        )

    def _upsert_relationship(
        self,
        source_id: int,
        target_id: int,
        relation_type: str,
        evidence: dict,
        db_session: Session,
    ) -> Relationship:
        existing = (
            db_session.query(Relationship)
            .filter(
                or_(
                    and_(
                        Relationship.source_entity == source_id,
                        Relationship.target_entity == target_id,
                    ),
                    and_(
                        Relationship.source_entity == target_id,
                        Relationship.target_entity == source_id,
                    ),
                )
            )
            .first()
        )

        now = datetime.now(timezone.utc)

        if existing is not None:
            existing.weight = (existing.weight or 1.0) + 0.1
            existing.source_count = (existing.source_count or 1) + 1
            existing.last_seen_at = now
            existing.confidence = max(
                existing.confidence or 0.0, evidence.get("confidence", 0.5)
            )

            rel_evidence = RelationshipEvidence(
                relationship_id=existing.id,
                extraction_id=evidence.get("extraction_id"),
                news_id=evidence.get("news_id"),
                evidence_span=evidence.get("evidence_span"),
                confidence=evidence.get("confidence"),
            )
            db_session.add(rel_evidence)

            return existing

        rel = Relationship(
            source_entity=source_id,
            target_entity=target_id,
            relation_type=relation_type,
            weight=1.0,
            confidence=evidence.get("confidence", 0.5),
            first_seen_at=now,
            last_seen_at=now,
            source_count=1,
        )
        db_session.add(rel)
        db_session.flush()

        rel_evidence = RelationshipEvidence(
            relationship_id=rel.id,
            extraction_id=evidence.get("extraction_id"),
            news_id=evidence.get("news_id"),
            evidence_span=evidence.get("evidence_span"),
            confidence=evidence.get("confidence"),
        )
        db_session.add(rel_evidence)

        return rel

    def _get_co_occurrence_type(
        self, entity_a: CanonicalEntity, entity_b: CanonicalEntity
    ) -> str:
        type_a = (entity_a.entity_type or "").lower()
        type_b = (entity_b.entity_type or "").lower()

        acquisition_types = {
            "company", "acquirer", "acquiree", "corporation", "holding",
        }
        investment_types = {
            "investor", "investment_firm", "venture_capital", "vc",
            "angel", "fund", "bank",
        }
        partnership_types = {
            "partner", "collaborator", "alliance", "joint_venture",
        }

        if type_a in acquisition_types and type_b in acquisition_types:
            return "acquired"
        if type_a in investment_types or type_b in investment_types:
            return "invested_in"
        if type_a in partnership_types or type_b in partnership_types:
            return "partnered_with"

        return "co_occurrence"

    def _extract_relation_from_events(
        self, entity_id: int, events: list[GraphEvent]
    ) -> str | None:
        for event in events:
            if not event.event_type_raw:
                continue
            event_lower = event.event_type_raw.lower()
            if any(kw in event_lower for kw in _ACQUISITION_KEYWORDS):
                return "acquired"
            if any(kw in event_lower for kw in _INVESTMENT_KEYWORDS):
                return "invested_in"
            if any(kw in event_lower for kw in _PARTNERSHIP_KEYWORDS):
                return "partnered_with"
            if any(kw in event_lower for kw in _COMPETITOR_KEYWORDS):
                return "competitor"
        return None

    def get_entity_graph(
        self, entity_id: int, depth: int = 2, min_weight: float = 0.0
    ) -> dict:
        session = self.get_session()
        try:
            visited_entities: set[int] = set()
            visited_relationships: set[int] = set()
            entities_map: dict[int, dict[str, Any]] = {}
            relationships_map: dict[int, dict[str, Any]] = {}
            queue: deque[tuple[int, int]] = deque()
            queue.append((entity_id, 0))

            while queue:
                current_id, current_depth = queue.popleft()

                if current_id in visited_entities:
                    continue
                visited_entities.add(current_id)

                if current_id not in entities_map:
                    entity = (
                        session.query(CanonicalEntity)
                        .filter(CanonicalEntity.id == current_id)
                        .first()
                    )
                    if entity:
                        entities_map[current_id] = {
                            "id": entity.id,
                            "canonical_name": entity.canonical_name,
                            "entity_type": entity.entity_type,
                            "sector": entity.sector,
                        }

                if current_depth >= depth:
                    continue

                rels = (
                    session.query(Relationship)
                    .filter(
                        or_(
                            Relationship.source_entity == current_id,
                            Relationship.target_entity == current_id,
                        ),
                        Relationship.weight >= min_weight,
                    )
                    .all()
                )

                for rel in rels:
                    if rel.id not in visited_relationships:
                        visited_relationships.add(rel.id)
                        relationships_map[rel.id] = {
                            "id": rel.id,
                            "source_entity": rel.source_entity,
                            "target_entity": rel.target_entity,
                            "relation_type": rel.relation_type,
                            "weight": rel.weight,
                        }

                    neighbor = (
                        rel.target_entity
                        if rel.source_entity == current_id
                        else rel.source_entity
                    )
                    if neighbor not in visited_entities:
                        queue.append((neighbor, current_depth + 1))

            return {
                "entities": list(entities_map.values()),
                "relationships": list(relationships_map.values()),
            }
        finally:
            session.close()

    def get_graph_summary(self) -> dict:
        session = self.get_session()
        try:
            total_entities = session.query(CanonicalEntity).count()
            total_relationships = session.query(Relationship).count()

            entity_type_rows = (
                session.query(
                    CanonicalEntity.entity_type, func.count(CanonicalEntity.id)
                )
                .group_by(CanonicalEntity.entity_type)
                .all()
            )
            entity_types = {row[0]: row[1] for row in entity_type_rows}

            top_entities_rows = (
                session.query(
                    CanonicalEntity.id,
                    CanonicalEntity.canonical_name,
                    func.count(Relationship.id).label("rel_count"),
                )
                .join(
                    Relationship,
                    or_(
                        Relationship.source_entity == CanonicalEntity.id,
                        Relationship.target_entity == CanonicalEntity.id,
                    ),
                )
                .group_by(CanonicalEntity.id, CanonicalEntity.canonical_name)
                .order_by(func.count(Relationship.id).desc())
                .limit(20)
                .all()
            )
            top_entities = [
                {"id": row[0], "name": row[1], "relationship_count": row[2]}
                for row in top_entities_rows
            ]

            return {
                "total_entities": total_entities,
                "total_relationships": total_relationships,
                "entity_types": entity_types,
                "top_entities": top_entities,
            }
        finally:
            session.close()

    def run_full_graph_build(self, batch_size: int = 100) -> dict:
        stats = {
            "processed": 0,
            "relationships_created": 0,
            "relationships_updated": 0,
            "errors": 0,
        }

        r = self._get_redis()
        last_id = 0
        if r is not None:
            try:
                val = r.get(_REDIS_CURSOR_KEY)
                if val is not None:
                    last_id = int(val)
            except Exception as e:
                logger.warning("Failed to read Redis cursor: %s", e)

        session = self.get_session()
        try:
            while True:
                batch = (
                    session.query(EntityResolutionLog.extraction_id)
                    .filter(EntityResolutionLog.extraction_id > last_id)
                    .distinct()
                    .order_by(EntityResolutionLog.extraction_id)
                    .limit(batch_size)
                    .all()
                )

                if not batch:
                    break

                for (extraction_id,) in batch:
                    try:
                        rels = self.build_relationships_for_extraction(extraction_id)
                        stats["processed"] += 1

                        for rel in rels:
                            if rel.source_count == 1 and abs(
                                (rel.weight or 1.0) - 1.0
                            ) < 0.01:
                                stats["relationships_created"] += 1
                            else:
                                stats["relationships_updated"] += 1
                    except Exception as e:
                        logger.error(
                            "Failed to build relationships for extraction %s: %s",
                            extraction_id,
                            e,
                        )
                        stats["errors"] += 1

                    last_id = extraction_id

                if r is not None:
                    try:
                        r.set(_REDIS_CURSOR_KEY, last_id)
                    except Exception as e:
                        logger.warning("Failed to update Redis cursor: %s", e)

                if len(batch) < batch_size:
                    break

            logger.info(
                "Full graph build complete — processed=%s, created=%s, updated=%s, errors=%s",
                stats["processed"],
                stats["relationships_created"],
                stats["relationships_updated"],
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
