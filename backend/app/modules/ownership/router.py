"""API مالکیت داده."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant, require_roles
from app.core.security import Actor
from app.modules.integrations.models import Tenant
from app.modules.ownership import service as svc

router = APIRouter(prefix="/ownership-policies", tags=["ownership"])


class PolicyUpsert(BaseModel):
    model_config = {"extra": "forbid"}
    entity_type: str = Field(min_length=3, max_length=40)
    field_group: str = Field(min_length=3, max_length=60)
    owner_type: str = Field(pattern="^(role|service|installation)$")
    owner_code: str = Field(min_length=2, max_length=80)


@router.get("")
def list_policies(actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                  db: Session = Depends(get_db)):
    return {"items": [{
        "id": str(p.id), "entity_type": p.entity_type, "field_group": p.field_group,
        "owner_type": p.owner_type, "owner_code": p.owner_code, "version": p.version,
        "status": p.status, "updated_by": p.updated_by, "updated_at": p.updated_at.isoformat(),
    } for p in svc.list_policies(db, tenant.id)]}


@router.put("")
def upsert_policy(payload: PolicyUpsert, request: Request,
                  actor: Actor = Depends(require_roles("steward", "tenant_admin", "integration_admin")),
                  tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    policy = svc.upsert_policy(db, tenant.id, actor, payload.entity_type, payload.field_group,
                               payload.owner_type, payload.owner_code, request=request)
    db.commit()
    return {"id": str(policy.id), "entity_type": policy.entity_type, "field_group": policy.field_group,
            "owner_type": policy.owner_type, "owner_code": policy.owner_code, "version": policy.version}
