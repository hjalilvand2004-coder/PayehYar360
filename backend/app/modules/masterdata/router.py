"""API اطلاعات پایه چندسامانه‌ای — مدیریت + سرویس‌دهی عمومی به سایر سامانه‌ها با کلید API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant, require_roles
from app.core.errors import unauthorized
from app.core.security import Actor
from app.modules.masterdata import service as svc
from app.modules.masterdata.models import ServiceClient
from app.modules.integrations.models import Tenant

router = APIRouter(tags=["masterdata"])

# ---------- مدل‌های ورودی ----------


class ImportItems(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict] = Field(min_length=1)
    source: str = "manual"


class ServiceClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=60)
    title: str | None = None
    scopes: list[str] = Field(default_factory=list)  # خالی = همه دامنه‌ها
    note: str | None = None


# ---------- مسیرهای مدیریتی (نقش steward/admin) ----------


@router.get("/masterdata/catalog")
def catalog(actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
            tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.catalog(db, tenant.id)


@router.get("/masterdata/instructors")
def list_instructors(search: str | None = None, limit: int = 500,
                     actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
                     tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_instructors(db, tenant.id, search, limit)}


@router.get("/masterdata/classrooms")
def list_classrooms(search: str | None = None, limit: int = 500,
                    actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
                    tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_classrooms(db, tenant.id, search, limit)}


@router.post("/masterdata/import/instructors", status_code=201)
def import_instructors(payload: ImportItems, request: Request,
                       actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                       tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.import_instructors(db, tenant.id, actor, payload.items, payload.source)
    db.commit()
    return out


@router.post("/masterdata/import/classrooms", status_code=201)
def import_classrooms(payload: ImportItems, request: Request,
                      actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                      tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.import_classrooms(db, tenant.id, actor, payload.items, payload.source)
    db.commit()
    return out


@router.post("/masterdata/sync/instructors")
def sync_instructors(request: Request,
                     actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                     tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.sync_instructors_from_source(db, tenant.id, actor)


@router.post("/masterdata/sync/classrooms")
def sync_classrooms(request: Request,
                    actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                    tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.sync_classrooms_from_source(db, tenant.id, actor)


@router.get("/masterdata/fetch-logs")
def fetch_logs(direction: str | None = None, domain: str | None = None, limit: int = 100,
               actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
               tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_logs(db, tenant.id, direction, domain, limit)}


@router.get("/masterdata/service-clients")
def list_clients(actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                 tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_service_clients(db, tenant.id)}


@router.post("/masterdata/service-clients", status_code=201)
def create_client(payload: ServiceClientCreate, request: Request,
                  actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                  tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.create_service_client(db, tenant.id, actor, payload.model_dump())
    db.commit()
    return out


@router.post("/masterdata/service-clients/{client_id}/revoke")
def revoke_client(client_id: uuid.UUID, request: Request,
                  actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                  tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.revoke_service_client(db, tenant.id, client_id)
    db.commit()
    return out


# ---------- سرویس عمومی برای سایر سامانه‌ها (احراز با X-API-Key) ----------


def _service_client_from_key(request: Request, db: Session = Depends(get_db),
                             x_api_key: str | None = Header(default=None)) -> ServiceClient:
    return svc.authenticate_service(db, x_api_key or "")


@router.get("/services/masterdata/{domain}")
def service_masterdata(domain: str, since: str | None = None,
                       tenant_client: ServiceClient = Depends(_service_client_from_key),
                       db: Session = Depends(get_db)):
    """نقطه اتصال همه سامانه‌های اکوسیستم برای گرفتن اطلاعات پایه — هر واکشی لاگ می‌شود."""
    endpoint = f"/api/v1/services/masterdata/{domain}" + (f"?since={since}" if since else "")
    return svc.fetch_domain(db, tenant_client, domain, since, endpoint)
