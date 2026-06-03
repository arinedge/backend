import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, func as sa_func
from app.database import get_db
from app.models.service_monitor import ServiceRegistry, ServiceRun, TableMetadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Monitoring"])


@router.get("/services")
def list_services(db: Session = Depends(get_db)):
    services = db.query(ServiceRegistry).order_by(ServiceRegistry.service_name).all()
    result = []
    for s in services:
        latest_run = db.query(ServiceRun).filter(
            ServiceRun.service_name == s.service_name
        ).order_by(ServiceRun.started_at.desc()).first()

        recent_runs = db.query(ServiceRun).filter(
            ServiceRun.service_name == s.service_name
        ).order_by(ServiceRun.started_at.desc()).limit(10).all()

        result.append({
            "id": s.id,
            "service_name": s.service_name,
            "display_name": s.display_name,
            "description": s.description,
            "service_type": s.service_type,
            "schedule": s.schedule,
            "enabled": s.enabled,
            "config": s.config,
            "latest_run": {
                "status": latest_run.status if latest_run else None,
                "started_at": latest_run.started_at.isoformat() if latest_run and latest_run.started_at else None,
                "duration_ms": latest_run.duration_ms if latest_run else None,
                "duration_seconds": round(latest_run.duration_ms / 1000, 1) if latest_run and latest_run.duration_ms else None,
                "records_processed": latest_run.records_processed if latest_run else 0,
                "error_message": latest_run.error_message if latest_run else None,
            } if latest_run else None,
            "recent_runs": [
                {
                    "run_id": r.run_id,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "duration_ms": r.duration_ms,
                    "records_processed": r.records_processed,
                }
                for r in recent_runs
            ],
            "created_at": str(s.created_at) if s.created_at else None,
            "updated_at": str(s.updated_at) if s.updated_at else None,
        })
    return result


@router.get("/services/{service_name}")
def get_service(service_name: str, db: Session = Depends(get_db)):
    s = db.query(ServiceRegistry).filter(ServiceRegistry.service_name == service_name).first()
    if not s:
        raise HTTPException(status_code=404, detail="Service not found")
    return {
        "id": s.id,
        "service_name": s.service_name,
        "display_name": s.display_name,
        "description": s.description,
        "service_type": s.service_type,
        "schedule": s.schedule,
        "enabled": s.enabled,
        "config": s.config,
    }


@router.get("/services/{service_name}/runs")
def get_service_runs(
    service_name: str,
    limit: int = Query(50, ge=1, le=500),
    status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(ServiceRun).filter(ServiceRun.service_name == service_name)
    if status:
        q = q.filter(ServiceRun.status == status)
    runs = q.order_by(ServiceRun.started_at.desc()).limit(limit).all()
    return [
        {
            "run_id": r.run_id,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "duration_ms": r.duration_ms,
            "duration_seconds": round(r.duration_ms / 1000, 1) if r.duration_ms else None,
            "records_processed": r.records_processed,
            "records_failed": r.records_failed,
            "error_message": r.error_message,
            "triggered_by": r.triggered_by,
        }
        for r in runs
    ]


@router.get("/tables")
def list_tables(db: Session = Depends(get_db)):
    tables = db.query(TableMetadata).order_by(TableMetadata.table_name).all()
    return [
        {
            "table_name": t.table_name,
            "schema_name": t.schema_name,
            "row_count": t.row_count,
            "total_size_bytes": t.total_size_bytes,
            "total_size_mb": round(t.total_size_bytes / (1024 * 1024), 2) if t.total_size_bytes else 0,
            "last_updated": t.last_updated.isoformat() if t.last_updated else None,
            "last_checked_at": t.last_checked_at.isoformat() if t.last_checked_at else None,
        }
        for t in tables
    ]


@router.get("/tables/{table_name}")
def get_table(table_name: str, db: Session = Depends(get_db)):
    t = db.query(TableMetadata).filter(TableMetadata.table_name == table_name).first()
    if not t:
        raise HTTPException(status_code=404, detail="Table not found")
    return {
        "table_name": t.table_name,
        "schema_name": t.schema_name,
        "row_count": t.row_count,
        "total_size_bytes": t.total_size_bytes,
        "total_size_mb": round(t.total_size_bytes / (1024 * 1024), 2) if t.total_size_bytes else 0,
        "last_updated": t.last_updated.isoformat() if t.last_updated else None,
        "last_checked_at": t.last_checked_at.isoformat() if t.last_checked_at else None,
    }


@router.post("/tables/refresh")
def refresh_table_metadata(db: Session = Depends(get_db)):
    table_names = db.execute(
        text("""
            SELECT tablename FROM pg_catalog.pg_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY tablename
        """)
    ).all()

    results = []
    for (tname,) in table_names:
        try:
            count = db.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar() or 0

            size = db.execute(
                text("SELECT pg_total_relation_size(:full)"),
                {"full": f"public.{tname}"},
            ).scalar() or 0

            last_updated = db.execute(
                text(f"""
                    SELECT MAX(created_at) FROM "{tname}"
                    WHERE created_at IS NOT NULL
                """)
            ).scalar()

            existing = db.query(TableMetadata).filter(TableMetadata.table_name == tname).first()
            if existing:
                existing.row_count = count
                existing.total_size_bytes = size
                existing.last_checked_at = datetime.now(timezone.utc)
                if last_updated:
                    existing.last_updated = last_updated
            else:
                tm = TableMetadata(
                    table_name=tname,
                    schema_name="public",
                    row_count=count,
                    total_size_bytes=size,
                    last_updated=last_updated,
                    last_checked_at=datetime.now(timezone.utc),
                )
                db.add(tm)

            results.append({"table_name": tname, "row_count": count, "total_size_bytes": size})
        except Exception as e:
            logger.warning(f"Failed to get metadata for {tname}: {e}")

    db.commit()
    return {"tables": results, "count": len(results)}


@router.get("/dashboard")
def dashboard_summary(db: Session = Depends(get_db)):
    total_services = db.query(sa_func.count(ServiceRegistry.id)).scalar() or 0
    enabled_services = db.query(sa_func.count(ServiceRegistry.id)).filter(ServiceRegistry.enabled == True).scalar() or 0

    last_24h = db.query(sa_func.count(ServiceRun.id)).filter(
        ServiceRun.started_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    ).scalar() or 0

    failed_recent = db.query(sa_func.count(ServiceRun.id)).filter(
        ServiceRun.status == "failed",
        ServiceRun.started_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    ).scalar() or 0

    running_now = db.query(sa_func.count(ServiceRun.id)).filter(
        ServiceRun.status == "running"
    ).scalar() or 0

    total_tables = db.query(sa_func.count(TableMetadata.id)).scalar() or 0
    total_rows = db.query(sa_func.coalesce(sa_func.sum(TableMetadata.row_count), 0)).scalar() or 0

    return {
        "services": {
            "total": total_services,
            "enabled": enabled_services,
            "running_now": running_now,
        },
        "runs_today": {
            "total": last_24h,
            "failed": failed_recent,
            "success_rate": round((last_24h - failed_recent) / last_24h * 100, 1) if last_24h > 0 else 100,
        },
        "tables": {
            "total": total_tables,
            "total_rows": total_rows,
        },
    }
