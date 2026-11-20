"""API فهرست‌های مرجع."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant
from app.core.security import Actor
from app.modules.integrations.models import Tenant
from app.modules.references import service as svc

router = APIRouter(prefix="/reference-sets", tags=["references"])


class SetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    owner_installation_id: uuid.UUID | None = None


class ItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    sort_order: int = 0
    valid_from: str | None = None
    valid_to: str | None = None


class ItemPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    sort_order: int | None = None
    status: str | None = None  # active | retired
    valid_from: str | None = None
    valid_to: str | None = None


@router.get("")
def list_sets(actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
              db: Session = Depends(get_db)):
    return {"items": svc.list_sets(db, tenant.id)}


@router.post("", status_code=201)
def create_set(payload: SetCreate, request: Request, actor: Actor = Depends(get_actor),
               tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.create_set(db, tenant.id, actor, payload.model_dump(), request=request)
    db.commit()
    return out


@router.get("/{code}/items")
def list_items(code: str, include_retired: bool = True, actor: Actor = Depends(get_actor),
               tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_items(db, tenant.id, code, include_retired)}


@router.post("/{code}/items", status_code=201)
def create_item(code: str, payload: ItemCreate, request: Request, actor: Actor = Depends(get_actor),
                tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.create_item(db, tenant.id, actor, code, payload.model_dump(), request=request)
    db.commit()
    return out


@router.patch("/{code}/items/{item_id}")
def patch_item(code: str, item_id: uuid.UUID, payload: ItemPatch, request: Request,
               actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
               db: Session = Depends(get_db)):
    out = svc.update_item(db, tenant.id, actor, code, item_id, payload.model_dump(exclude_none=True),
                          request=request)
    db.commit()
    return out
