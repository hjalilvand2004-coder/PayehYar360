"""API کیفیت داده."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant, require_roles
from app.core.security import Actor
from app.modules.data_quality import service as svc
from app.modules.integrations.models import Tenant

router = APIRouter(tags=["quality"])


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_ids: list[str] = Field(min_length=2)
    evidence: dict | None = None


class MergeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_person_id: str
    note: str | None = None


class ReverseDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = None


@router.get("/quality/overview")
def quality_overview(actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
                     tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    """داشبورد تجمیعی کیفیت داده: امتیاز، ابعاد، حوزه‌ها و ۱۷ بررسی با drill-down."""
    from app.modules.data_quality import insights
    return insights.run_overview(db, tenant.id)


@router.get("/quality/duplicate-scan")
def duplicate_scan(actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                   tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.scan_duplicates(db, tenant.id)}


@router.post("/quality/cases", status_code=201)
def create_case(payload: CaseCreate, request: Request,
                actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.create_case(db, tenant.id, actor, payload.model_dump(), request=request)
    db.commit()
    return out


@router.get("/resolution-cases")
def list_cases(status: str | None = None, limit: int = 50,
               actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
               tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_cases(db, tenant.id, status, limit)}


@router.post("/resolution-cases/{case_id}/merge")
def decide_merge(case_id: uuid.UUID, payload: MergeDecision, request: Request,
                 actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                 tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.decide_merge(db, tenant.id, actor, case_id, payload.target_person_id, payload.note,
                           request=request, correlation_id=getattr(request.state, "correlation_id", None))
    db.commit()
    return out


@router.post("/merges/{merge_id}/reverse")
def reverse_merge(merge_id: uuid.UUID, payload: ReverseDecision, request: Request,
                  actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                  tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.reverse_merge(db, tenant.id, actor, merge_id, payload.note, request=request)
    db.commit()
    return out


@router.get("/merges")
def list_merges(actor: Actor = Depends(require_roles("steward", "tenant_admin", "auditor")),
                tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_merge_records(db, tenant.id)}
