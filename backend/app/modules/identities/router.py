"""API هویت و نگاشت شناسه."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.common.idempotency import execute_idempotent
from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant
from app.core.security import Actor
from app.modules.identities import service as svc
from app.modules.integrations.models import Tenant

router = APIRouter(tags=["identity"])


class LinkCreate(BaseModel):
    model_config = {"extra": "forbid"}
    person_id: uuid.UUID
    issuer: str | None = None
    subject: str = Field(min_length=2, max_length=200)
    account_label: str | None = None
    note: str | None = None


class LinkRevoke(BaseModel):
    model_config = {"extra": "forbid"}
    note: str | None = None


class MappingCreate(BaseModel):
    model_config = {"extra": "forbid"}
    installation_id: uuid.UUID | None = None
    installation_code: str | None = None
    entity_type: str = Field(min_length=3, max_length=40)
    local_id: str = Field(min_length=1, max_length=150)
    entity_id: uuid.UUID
    note: str | None = None


class MappingResolve(BaseModel):
    model_config = {"extra": "forbid"}
    installation_id: uuid.UUID | None = None
    installation_code: str | None = None
    entity_type: str
    local_id: str


@router.get("/identity/me")
def me(actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.resolve_me(db, tenant.id, actor)


@router.post("/identity-account-links", status_code=201)
def link_account(request: Request, payload: LinkCreate,
                 idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                 actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                 db: Session = Depends(get_db)):
    correlation_id = getattr(request.state, "correlation_id", None)
    result = execute_idempotent(
        db, tenant.id, idempotency_key, actor, payload.model_dump(),
        lambda: (201, svc.link_account(db, tenant.id, actor, payload.model_dump(), request=request,
                                       correlation_id=correlation_id)),
    )
    return Response(content=json.dumps(result.body, ensure_ascii=False), status_code=result.status,
                    media_type="application/json",
                    headers={"Idempotent-Replay": "true"} if result.replayed else None)


@router.post("/identity-account-links/{link_id}/revoke")
def revoke_link(link_id: uuid.UUID, payload: LinkRevoke,
                actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                db: Session = Depends(get_db), request: Request = None):
    out = svc.revoke_link(db, tenant.id, actor, link_id, payload.note, request=request)
    db.commit()
    return out


@router.get("/persons/{person_id}/account-links")
def person_links(person_id: uuid.UUID, actor: Actor = Depends(get_actor),
                 tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    from app.modules.identities.repository import list_person_links
    return {"items": [{
        "id": str(l.id), "issuer": l.issuer, "subject": l.subject, "account_label": l.account_label,
        "status": l.status, "linked_at": l.linked_at,
    } for l in list_person_links(db, tenant.id, person_id)]}


@router.post("/id-mappings", status_code=201)
def create_mapping(request: Request, payload: MappingCreate,
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                   actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                   db: Session = Depends(get_db)):
    correlation_id = getattr(request.state, "correlation_id", None)
    result = execute_idempotent(
        db, tenant.id, idempotency_key, actor, payload.model_dump(exclude_none=True),
        lambda: (201, svc.register_mapping(db, tenant.id, actor, payload.model_dump(exclude_none=True),
                                           request=request, correlation_id=correlation_id)),
    )
    return Response(content=json.dumps(result.body, ensure_ascii=False), status_code=result.status,
                    media_type="application/json",
                    headers={"Idempotent-Replay": "true"} if result.replayed else None)


@router.post("/id-mappings/resolve")
def resolve_mapping(request: Request, payload: MappingResolve,
                    actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                    db: Session = Depends(get_db)):
    return svc.resolve_mapping(db, tenant.id, actor, payload.model_dump(exclude_none=True), request=request)


@router.get("/id-mappings")
def list_mappings(installation_code: str | None = None, entity_type: str | None = None,
                  entity_id: str | None = None, limit: int = 50, offset: int = 0,
                  actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                  db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    return {"items": svc.search_mappings(db, tenant.id, installation_code, entity_type, entity_id, limit, offset)}
