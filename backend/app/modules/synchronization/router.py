"""API همگام‌سازی."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant, require_scope
from app.core.security import Actor
from app.modules.integrations.models import Tenant
from app.modules.synchronization import service as svc

router = APIRouter(prefix="/sync", tags=["synchronization"])


class SnapshotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entities: list[str] | None = None   # persons, organizations, account_links, mappings
    installation_id: uuid.UUID | None = None


class CheckpointIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installation_id: uuid.UUID | None = None
    installation_code: str | None = None
    scope: str = "persons"
    cursor: int
    note: str | None = None


class ReconciliationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    installation_id: uuid.UUID | None = None
    installation_code: str | None = None
    scope: str = "persons"


@router.post("/snapshots", status_code=202)
def create_snapshot(request: Request, payload: SnapshotCreate,
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                    actor: Actor = Depends(require_scope("sync")), tenant: Tenant = Depends(get_tenant),
                    db: Session = Depends(get_db)):
    job = svc.create_snapshot_job(db, tenant.id, actor, payload.model_dump(exclude_none=True), request=request)
    db.commit()
    return svc._job_out(job)


@router.get("/snapshots/{job_id}")
def snapshot_status(job_id: uuid.UUID, actor: Actor = Depends(require_scope("sync")),
                    tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc._job_out(svc.get_snapshot_job(db, tenant.id, job_id))


@router.get("/snapshots/{job_id}/download")
def snapshot_download(job_id: uuid.UUID, actor: Actor = Depends(require_scope("sync")),
                      tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    job = svc.get_snapshot_job(db, tenant.id, job_id)
    path = svc.snapshot_file(job)
    return FileResponse(path, media_type="application/json", filename=f"snapshot-{job.id}.json")


@router.get("/changes")
def list_changes(cursor: int | None = None, limit: int = 100,
                 actor: Actor = Depends(require_scope("sync")), tenant: Tenant = Depends(get_tenant),
                 db: Session = Depends(get_db)):
    limit = max(1, min(limit, 1000))
    return svc.list_changes(db, tenant.id, cursor, limit)


@router.post("/checkpoints")
def upsert_checkpoint(request: Request, payload: CheckpointIn,
                      actor: Actor = Depends(require_scope("sync")), tenant: Tenant = Depends(get_tenant),
                      db: Session = Depends(get_db)):
    out = svc.upsert_checkpoint(db, tenant.id, actor, payload.model_dump(exclude_none=True), request=request)
    db.commit()
    return out


@router.post("/reconciliation/jobs")
def reconciliation_job(request: Request, payload: ReconciliationIn,
                       actor: Actor = Depends(require_scope("sync")), tenant: Tenant = Depends(get_tenant),
                       db: Session = Depends(get_db)):
    out = svc.create_reconciliation_job(db, tenant.id, actor, payload.model_dump(exclude_none=True), request=request)
    db.commit()
    return out
