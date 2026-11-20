"""API سازمان‌ها."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant
from app.core.errors import AppError
from app.core.security import Actor
from app.modules.integrations.models import Tenant
from app.modules.organizations import schemas as S, service as svc

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _parse_if_match(if_match: str | None) -> int:
    if not if_match:
        raise AppError("VERSION_REQUIRED", "ارسال هدر If-Match با نسخه فعلی الزامی است.", 400)
    token = if_match.strip().removeprefix("W/").strip('"')
    try:
        return int(token)
    except ValueError:
        raise AppError("INVALID_IF_MATCH", "هدر If-Match باید شماره نسخه باشد.", 400)


@router.get("")
def list_orgs(actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
              db: Session = Depends(get_db)):
    return {"items": svc.list_tree(db, tenant.id)}


@router.post("", status_code=201)
def create_org(payload: S.OrganizationCreate, request: Request,
               actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
               db: Session = Depends(get_db)):
    out = svc.create_org(db, tenant.id, actor, payload.model_dump(), request=request,
                         correlation_id=getattr(request.state, "correlation_id", None))
    db.commit()
    return out


@router.patch("/{org_id}")
def patch_org(org_id: uuid.UUID, payload: S.OrganizationUpdate,
              if_match: str | None = Header(default=None, alias="If-Match"),
              request: Request = None, actor: Actor = Depends(get_actor),
              tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    expected = _parse_if_match(if_match)
    out = svc.update_org(db, tenant.id, actor, org_id, payload.model_dump(exclude_none=True), expected,
                         request=request, correlation_id=getattr(request.state, "correlation_id", None))
    db.commit()
    return out
