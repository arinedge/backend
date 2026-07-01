from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_admin_user
from app.services.graph_service import GraphService
from app.components.graph.pipeline import GraphPipeline
from app.models.graph import CanonicalEntity, Relationship
from app.schemas.graph import (
    CanonicalEntityOut,
    CanonicalEntityDetail,
    GraphEventOut,
    RelationshipOut,
    GraphMetricOut,
    EntitySearchParams,
    EntityMergeRequest,
    RelationshipOverrideRequest,
    GraphDataResponse,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Graph"])


@router.get("/entities", response_model=list[CanonicalEntityOut])
def search_entities(
    query: str | None = Query(None),
    entity_type: str | None = Query(None),
    sector: str | None = Query(None),
    ticker: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    service = GraphService(db)
    params = EntitySearchParams(
        query=query,
        entity_type=entity_type,
        sector=sector,
        ticker=ticker,
        limit=limit,
        offset=offset,
    )
    items, total = service.search_entities(params)
    return [CanonicalEntityOut.model_validate(e) for e in items]


@router.get("/entities/{entity_id}", response_model=CanonicalEntityDetail)
def get_entity(entity_id: int, db: Session = Depends(get_db)):
    service = GraphService(db)
    entity = service.get_entity_detail(entity_id)
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    return CanonicalEntityDetail.model_validate(entity)


@router.get("/entities/{entity_id}/graph", response_model=GraphDataResponse)
def get_entity_graph(
    entity_id: int,
    depth: int = Query(2, ge=1, le=5),
    min_weight: float = Query(0.0, ge=0.0),
    db: Session = Depends(get_db),
):
    service = GraphService(db)
    entity = service.get_entity_detail(entity_id)
    if not entity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")

    result = service.get_entity_graph(entity_id, depth=depth, min_weight=min_weight)

    entity_ids = [e["id"] for e in result.get("entities", [])]
    relationship_ids = [r["id"] for r in result.get("relationships", [])]

    entities = (
        db.query(CanonicalEntity)
        .filter(CanonicalEntity.id.in_(entity_ids))
        .all()
    ) if entity_ids else []
    relationships = (
        db.query(Relationship)
        .filter(Relationship.id.in_(relationship_ids))
        .all()
    ) if relationship_ids else []

    return GraphDataResponse(
        entities=[CanonicalEntityOut.model_validate(e) for e in entities],
        relationships=[RelationshipOut.model_validate(r) for r in relationships],
    )


@router.get("/entities/{entity_id}/events", response_model=list[GraphEventOut])
def get_entity_events(
    entity_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    service = GraphService(db)
    events, total = service.get_entity_events(entity_id, limit=limit, offset=offset)
    return [GraphEventOut.model_validate(e) for e in events]


@router.get("/entities/{entity_id}/metrics", response_model=GraphMetricOut)
def get_entity_metrics(entity_id: int, db: Session = Depends(get_db)):
    service = GraphService(db)
    metrics = service.get_entity_metrics(entity_id)
    if not metrics:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metrics not found")
    return GraphMetricOut.model_validate(metrics)


@router.get("/entities/{entity_id}/relationships", response_model=list[RelationshipOut])
def get_entity_relationships(
    entity_id: int,
    relation_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    service = GraphService(db)
    rels = service.get_entity_relationships(entity_id, relation_type=relation_type)
    return [RelationshipOut.model_validate(r) for r in rels]


@router.get("/summary")
def get_graph_summary(db: Session = Depends(get_db)):
    service = GraphService(db)
    return service.get_graph_summary()


@router.get("/influence")
def get_top_influencers(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    service = GraphService(db)
    return service.get_top_influencers(limit=limit)


@router.get("/influence/path")
def get_influence_path(source_id: int = Query(...), target_id: int = Query(...), db: Session = Depends(get_db)):
    service = GraphService(db)
    path = service.get_influence_path(source_id, target_id)
    if not path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Influence path not found")
    return path


@router.post("/pipeline/run-incremental", dependencies=[Depends(get_current_admin_user)])
def run_incremental_pipeline():
    pipeline = GraphPipeline()
    return pipeline.run_incremental()


@router.post("/pipeline/run-full", dependencies=[Depends(get_current_admin_user)])
def run_full_pipeline():
    pipeline = GraphPipeline()
    return pipeline.run_full()


@router.post("/pipeline/reset-cursors", dependencies=[Depends(get_current_admin_user)])
def reset_pipeline_cursors():
    pipeline = GraphPipeline()
    return pipeline.reset_cursors()


@router.post("/pipeline/reprocess/{extraction_id}", dependencies=[Depends(get_current_admin_user)])
def reprocess_extraction(extraction_id: int):
    pipeline = GraphPipeline()
    return pipeline.run_single_extraction(extraction_id)


@router.get("/pipeline/status")
def get_pipeline_status():
    pipeline = GraphPipeline()
    return pipeline.get_pipeline_status()


@router.post("/admin/merge-entities", dependencies=[Depends(get_current_admin_user)])
def merge_entities(request: EntityMergeRequest, db: Session = Depends(get_db)):
    service = GraphService(db)
    return service.merge_entities(request)


@router.put("/admin/relationships/{relationship_id}", response_model=RelationshipOut, dependencies=[Depends(get_current_admin_user)])
def override_relationship(relationship_id: int, request: RelationshipOverrideRequest, db: Session = Depends(get_db)):
    service = GraphService(db)
    request.relationship_id = relationship_id
    rel = service.override_relationship(request)
    if not rel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found")
    return RelationshipOut.model_validate(rel)
