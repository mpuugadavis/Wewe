"""Durable worker health state for operational monitoring."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import WorkerHealth

def _now(): return datetime.now(timezone.utc)

def _get_or_create(db: Session, worker_name: str):
    row = db.get(WorkerHealth, worker_name)
    if row is None:
        row = WorkerHealth(worker_name=worker_name, status="STARTING")
        db.add(row); db.flush()
    return row

def mark_started(db: Session, worker_name: str) -> None:
    row=_get_or_create(db, worker_name); now=_now()
    row.status="RUNNING"; row.last_started_at=now; row.last_heartbeat_at=now
    row.last_error=None; row.updated_at=now; db.commit()

def mark_heartbeat(db: Session, worker_name: str) -> None:
    row=_get_or_create(db, worker_name); now=_now()
    row.status="RUNNING"; row.last_heartbeat_at=now; row.updated_at=now; db.commit()

def mark_success(db: Session, worker_name: str, *, duration_ms: int, processed: int=0, scanned: int=0, candidates: int=0, deleted: int=0, skipped: int=0, failed: int=0) -> None:
    row=_get_or_create(db, worker_name); now=_now()
    row.status="HEALTHY"; row.last_heartbeat_at=now; row.last_success_at=now
    row.last_duration_ms=duration_ms; row.last_processed=processed; row.last_scanned=scanned
    row.last_candidates=candidates; row.last_deleted=deleted; row.last_skipped=skipped; row.last_failed=failed
    row.last_error=None; row.updated_at=now; db.commit()

def mark_failure(db: Session, worker_name: str, *, duration_ms: int, error: str) -> None:
    row=_get_or_create(db, worker_name); now=_now()
    row.status="FAILING"; row.last_heartbeat_at=now; row.last_failure_at=now
    row.last_duration_ms=duration_ms; row.last_error=error[:1000]; row.updated_at=now; db.commit()

def worker_snapshot(db: Session, worker_name: str):
    row=db.scalar(select(WorkerHealth).where(WorkerHealth.worker_name==worker_name))
    if row is None: return None
    return {k:getattr(row,k) for k in ("worker_name","status","last_started_at","last_heartbeat_at","last_success_at","last_failure_at","last_duration_ms","last_processed","last_scanned","last_candidates","last_deleted","last_skipped","last_failed","last_error","updated_at")}
