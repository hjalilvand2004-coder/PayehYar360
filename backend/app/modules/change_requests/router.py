"""API درخواست اصلاح."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant, require_roles
from app.core.security import Actor
from app.modules.integrations.models import Tenant
from app.modules.change_requests import service as svc

router = APIRouter(prefix="/change-requests", tags=["change-requests"])


class ChangeRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str = "person"
    entity_id: uuid.UUID
    proposed_changes: dict[str, str] = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=1000)


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern="^(approve|reject|cancel)$")
    note: str | None = None


@router.post("", status_code=201)
def create_request(payload: ChangeRequestCreate, request: Request, actor: Actor = Depends(get_actor),
                   tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.create_request(db, tenant.id, actor, payload.model_dump(), request=request)
    db.commit()
    return out


@router.get("")
def list_requests(status: str | None = None, limit: int = 50, offset: int = 0,
                  actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                  db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    return svc.list_requests(db, tenant.id, status, limit, offset)


@router.post("/{cr_id}/decision")
def decide(cr_id: uuid.UUID, payload: DecisionIn, request: Request,
           actor: Actor = Depends(require_roles("steward", "tenant_admin")),
           tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.decide_request(db, tenant.id, actor, cr_id, payload.action, payload.note, request=request)
    db.commit()
    return out
