"""API مشتری‌ها، نصب‌ها، وضعیت اتصال و آمار داشبورد."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant, require_roles
from app.core.security import Actor
from app.modules.integrations import service as svc
from app.modules.integrations.models import Tenant

router = APIRouter(tags=["integrations"])

rabbitmq_state_holder = {"connected": False, "detail": "publishing disabled (RABBITMQ_URL خالی)"}


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    note: str | None = None


class InstallationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system_code: str = Field(min_length=2, max_length=60)
    installation_code: str = Field(min_length=2, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    mode: str = Field(default="integrated", pattern="^(local|integrated)$")
    base_url: str | None = None
    owner_scopes: str | None = None
    note: str | None = None


class InstallationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    mode: str | None = None
    status: str | None = None
    base_url: str | None = None
    owner_scopes: str | None = None
    note: str | None = None


@router.get("/tenants")
def list_tenants(actor: Actor = Depends(get_actor), db: Session = Depends(get_db)):
    return {"items": [{"id": str(t.id), "code": t.code, "name": t.name, "status": t.status,
                       "created_at": t.created_at.isoformat()} for t in svc.list_tenants(db)]}


@router.post("/tenants", status_code=201)
def create_tenant(payload: TenantCreate, request: Request,
                  actor: Actor = Depends(require_roles("tenant_admin", "integration_admin")),
                  db: Session = Depends(get_db)):
    tenant = svc.create_tenant(db, actor, payload.model_dump(), request=request)
    db.commit()
    return {"id": str(tenant.id), "code": tenant.code, "name": tenant.name, "status": tenant.status}


@router.get("/installations")
def list_installations(actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                       db: Session = Depends(get_db)):
    return {"items": [svc._inst_out(i) for i in svc.list_installations(db, tenant.id)]}


@router.post("/installations", status_code=201)
def create_installation(payload: InstallationCreate, request: Request,
                        actor: Actor = Depends(require_roles("integration_admin", "tenant_admin")),
                        tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    inst = svc.create_installation(db, tenant.id, actor, payload.model_dump(), request=request)
    db.commit()
    return svc._inst_out(inst)


@router.patch("/installations/{inst_id}")
def patch_installation(inst_id: uuid.UUID, payload: InstallationPatch, request: Request,
                       actor: Actor = Depends(require_roles("integration_admin", "tenant_admin")),
                       tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    inst = svc.update_installation(db, tenant.id, actor, inst_id, payload.model_dump(exclude_none=True),
                                   request=request)
    db.commit()
    return svc._inst_out(inst)


@router.get("/integrations/status")
def integrations_status(actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                        db: Session = Depends(get_db)):
    return svc.integrations_status(db, tenant.id, rabbitmq_state_holder)


@router.get("/stats")
def stats(actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
          db: Session = Depends(get_db)):
    return svc.tenant_stats(db, tenant.id)
