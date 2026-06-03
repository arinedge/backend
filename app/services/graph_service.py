from sqlalchemy import func, distinct, or_
from sqlalchemy.orm import Session, joinedload

from app.components.graph.graph_engine import GraphEngine
from app.components.graph.pipeline import GraphPipeline
from app.components.graph.propagation_engine import PropagationEngine
from app.models.graph import (
    CanonicalEntity,
    EntityAlias,
    EntityResolutionLog,
    GraphEvent,
    GraphMetric,
    Relationship,
)
from app.schemas.graph import (
    EntityMergeRequest,
    EntitySearchParams,
    RelationshipOverrideRequest,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GraphService:
    def __init__(self, db: Session):
        self.db = db

    def search_entities(
        self, params: EntitySearchParams
    ) -> tuple[list[CanonicalEntity], int]:
        query = self.db.query(CanonicalEntity)

        if params.query:
            query = query.filter(
                CanonicalEntity.canonical_name.ilike(f"%{params.query}%")
            )
        if params.entity_type:
            query = query.filter(CanonicalEntity.entity_type == params.entity_type)
        if params.sector:
            query = query.filter(CanonicalEntity.sector == params.sector)
        if params.ticker:
            query = query.filter(CanonicalEntity.ticker == params.ticker)

        total = query.count()
        items = (
            query.order_by(CanonicalEntity.canonical_name)
            .offset(params.offset)
            .limit(params.limit)
            .all()
        )
        return items, total

    def get_entity_detail(self, entity_id: int) -> CanonicalEntity | None:
        return (
            self.db.query(CanonicalEntity)
            .options(joinedload(CanonicalEntity.aliases))
            .filter(CanonicalEntity.id == entity_id)
            .first()
        )

    def get_entity_graph(
        self, entity_id: int, depth: int = 2, min_weight: float = 0.0
    ) -> dict:
        engine = GraphEngine(lambda: self.db)
        return engine.get_entity_graph(
            entity_id, depth=depth, min_weight=min_weight
        )

    def get_entity_events(
        self, entity_id: int, limit: int = 50, offset: int = 0
    ) -> tuple[list[GraphEvent], int]:
        base = self.db.query(GraphEvent).join(
            EntityResolutionLog,
            GraphEvent.extraction_id == EntityResolutionLog.extraction_id,
        ).filter(EntityResolutionLog.resolved_id == entity_id)

        total = (
            base.with_entities(func.count(distinct(GraphEvent.id))).scalar() or 0
        )

        events = (
            base.distinct(GraphEvent.id)
            .order_by(GraphEvent.id, GraphEvent.article_date.desc().nullslast())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return events, total

    def get_entity_metrics(self, entity_id: int) -> GraphMetric | None:
        return (
            self.db.query(GraphMetric)
            .filter(GraphMetric.entity_id == entity_id)
            .first()
        )

    def get_graph_summary(self) -> dict:
        engine = GraphEngine(lambda: self.db)
        return engine.get_graph_summary()

    def get_influence_path(
        self, source_id: int, target_id: int
    ) -> dict | None:
        engine = PropagationEngine(lambda: self.db)
        return engine.get_influence_path(source_id, target_id)

    def get_top_influencers(self, limit: int = 20) -> list[dict]:
        engine = PropagationEngine(lambda: self.db)
        return engine.get_top_influencers(limit=limit)

    def get_entity_relationships(
        self, entity_id: int, relation_type: str | None = None
    ) -> list[Relationship]:
        query = self.db.query(Relationship).filter(
            (Relationship.source_entity == entity_id)
            | (Relationship.target_entity == entity_id)
        )
        if relation_type:
            query = query.filter(Relationship.relation_type == relation_type)
        return query.all()

    def merge_entities(self, request: EntityMergeRequest) -> dict:
        target_id = request.target_id
        source_ids = request.source_ids

        aliases_moved = 0
        for source_id in source_ids:
            result = (
                self.db.query(EntityAlias)
                .filter(EntityAlias.canonical_id == source_id)
                .update({"canonical_id": target_id})
            )
            aliases_moved += result

        for source_id in source_ids:
            self.db.query(EntityResolutionLog).filter(
                EntityResolutionLog.resolved_id == source_id
            ).update({"resolved_id": target_id})

        relationships_updated = 0
        for source_id in source_ids:
            rels_as_source = (
                self.db.query(Relationship)
                .filter(Relationship.source_entity == source_id)
                .all()
            )
            for rel in rels_as_source:
                existing = (
                    self.db.query(Relationship)
                    .filter(
                        Relationship.source_entity == target_id,
                        Relationship.target_entity == rel.target_entity,
                        Relationship.id != rel.id,
                    )
                    .first()
                )
                if existing:
                    existing.weight = (
                        (existing.weight or 1.0) + (rel.weight or 1.0)
                    ) / 2
                    existing.source_count = (
                        existing.source_count or 1
                    ) + (rel.source_count or 1)
                    self.db.delete(rel)
                else:
                    rel.source_entity = target_id
                relationships_updated += 1

            rels_as_target = (
                self.db.query(Relationship)
                .filter(Relationship.target_entity == source_id)
                .all()
            )
            for rel in rels_as_target:
                existing = (
                    self.db.query(Relationship)
                    .filter(
                        Relationship.source_entity == rel.source_entity,
                        Relationship.target_entity == target_id,
                        Relationship.id != rel.id,
                    )
                    .first()
                )
                if existing:
                    existing.weight = (
                        (existing.weight or 1.0) + (rel.weight or 1.0)
                    ) / 2
                    existing.source_count = (
                        existing.source_count or 1
                    ) + (rel.source_count or 1)
                    self.db.delete(rel)
                else:
                    rel.target_entity = target_id
                relationships_updated += 1

        self.db.query(CanonicalEntity).filter(
            CanonicalEntity.id.in_(source_ids)
        ).delete(synchronize_session=False)

        self.db.commit()

        return {
            "merged": len(source_ids),
            "aliases_moved": aliases_moved,
            "relationships_updated": relationships_updated,
        }

    def override_relationship(
        self, request: RelationshipOverrideRequest
    ) -> Relationship | None:
        rel = (
            self.db.query(Relationship)
            .filter(Relationship.id == request.relationship_id)
            .first()
        )
        if rel is None:
            return None

        if request.relation_type is not None:
            rel.relation_type = request.relation_type
        if request.weight is not None:
            rel.weight = request.weight
        if request.confidence is not None:
            rel.confidence = request.confidence

        self.db.commit()
        self.db.refresh(rel)
        return rel

    def reprocess_extraction(self, extraction_id: int) -> dict:
        pipeline = GraphPipeline()
        return pipeline.run_single_extraction(extraction_id)
