"""API ماژول اشخاص — مسیرها نازک؛ منطق در service (بند ۶.۲)."""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.idempotency import execute_idempotent
from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant
from app.core.errors import AppError
from app.core.security import Actor
from app.modules.integrations.models import Tenant
from app.modules.persons import schemas as S, service as svc

router = APIRouter(prefix="/persons", tags=["persons"])


def _parse_if_match(if_match: str | None, body_version: int | None) -> int:
    if if_match:
        token = if_match.strip()
        if token.startswith("W/"):
            token = token[2:]
        token = token.strip('"')
        try:
            return int(token)
        except ValueError:
            raise AppError("INVALID_IF_MATCH", "هدر If-Match باید شماره نسخه باشد.", 400)
    if body_version is not None:
        return body_version
    raise AppError("VERSION_REQUIRED", "ارسال هدر If-Match با نسخه فعلی الزامی است.", 400)


class VersionIn(BaseModel):
    version: int | None = None


@router.get("")
def list_persons(request: Request, q: str | None = None, status: str | None = None,
                 identifier_type: str | None = None, identifier_value: str | None = None,
                 limit: int = 25, offset: int = 0,
                 actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                 db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    return svc.search_persons(db, tenant.id, actor, q, status, identifier_type, identifier_value, limit, offset)


@router.post("", status_code=201)
def create_person(request: Request, payload: S.PersonCreate,
                  idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                  actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                  db: Session = Depends(get_db)):
    correlation_id = getattr(request.state, "correlation_id", None)
    result = execute_idempotent(
        db, tenant.id, idempotency_key, actor, payload.model_dump(),
        lambda: (201, svc.create_person(db, tenant.id, actor, payload.model_dump(), request=request,
                                        correlation_id=correlation_id)),
    )
    return Response(content=json.dumps(result.body, ensure_ascii=False),
                    status_code=result.status, media_type="application/json",
                    headers={"Idempotent-Replay": "true"} if result.replayed else None)


@router.get("/{person_id}")
def get_person_detail(person_id: uuid.UUID, actor: Actor = Depends(get_actor),
                      tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.person_detail(db, tenant.id, person_id)


@router.patch("/{person_id}")
def patch_person(person_id: uuid.UUID, payload: S.PersonUpdate,
                 if_match: str | None = Header(default=None, alias="If-Match"),
                 actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                 db: Session = Depends(get_db), request: Request = None):
    changes = payload.model_dump(exclude_none=True)
    expected = _parse_if_match(if_match, None)
    correlation_id = getattr(request.state, "correlation_id", None) if request else None
    result = svc.update_person(db, tenant.id, actor, person_id, changes, expected,
                               request=request, correlation_id=correlation_id)
    db.commit()
    return result


@router.post("/{person_id}/deactivation")
def deactivate_person(person_id: uuid.UUID, payload: VersionIn,
                      if_match: str | None = Header(default=None, alias="If-Match"),
                      reason: str | None = None,
                      actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                      db: Session = Depends(get_db), request: Request = None):
    expected = _parse_if_match(if_match, payload.version)
    result = svc.deactivate_person(db, tenant.id, actor, person_id, expected, reason, request=request)
    db.commit()
    return result


@router.get("/{person_id}/history")
def person_history(person_id: uuid.UUID, actor: Actor = Depends(get_actor),
                   tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.history(db, tenant.id, person_id)}


@router.post("/{person_id}/identifiers", status_code=201)
def add_identifier(person_id: uuid.UUID, payload: S.IdentifierCreate,
                   actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                   db: Session = Depends(get_db), request: Request = None):
    out = svc.add_identifier(db, tenant.id, actor, person_id, payload.model_dump(), request=request)
    db.commit()
    return out


@router.patch("/{person_id}/identifiers/{identifier_id}")
def patch_identifier(person_id: uuid.UUID, identifier_id: uuid.UUID, payload: S.IdentifierPatch,
                     actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                     db: Session = Depends(get_db), request: Request = None):
    out = svc.patch_identifier(db, tenant.id, actor, person_id, identifier_id,
                               payload.model_dump(exclude_none=True), request=request)
    db.commit()
    return out


@router.post("/{person_id}/contacts", status_code=201)
def add_contact(person_id: uuid.UUID, payload: S.ContactCreate,
                actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                db: Session = Depends(get_db), request: Request = None):
    out = svc.add_contact(db, tenant.id, actor, person_id, payload.model_dump(), request=request)
    db.commit()
    return out


@router.patch("/{person_id}/contacts/{contact_id}")
def patch_contact(person_id: uuid.UUID, contact_id: uuid.UUID, payload: S.ContactPatch,
                  actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                  db: Session = Depends(get_db), request: Request = None):
    out = svc.patch_contact(db, tenant.id, actor, person_id, contact_id,
                            payload.model_dump(exclude_none=True), request=request)
    db.commit()
    return out
