"""منطق فهرست‌های مرجع با نسخه‌بندی (FR-06)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.events import EventType, build_event, record_audit, record_change
from app.core.errors import conflict, not_found
from app.core.security import Actor
from app.modules.ownership import service as ownership_svc
from app.modules.references.models import ReferenceItem, ReferenceSet


def _set_out(s: ReferenceSet) -> dict:
    return {"id": str(s.id), "code": s.code, "title": s.title, "description": s.description,
            "version": s.version, "status": s.status,
            "owner_installation_id": str(s.owner_installation_id) if s.owner_installation_id else None,
            "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat()}


def _item_out(i: ReferenceItem) -> dict:
    return {"id": str(i.id), "set_id": str(i.set_id), "parent_id": str(i.parent_id) if i.parent_id else None,
            "code": i.code, "title": i.title, "sort_order": i.sort_order, "status": i.status,
            "valid_from": i.valid_from, "valid_to": i.valid_to}


def get_set(db: Session, tenant_id, code: str) -> ReferenceSet:
    s = db.execute(select(ReferenceSet).where(
        ReferenceSet.tenant_id == tenant_id, ReferenceSet.code == code)).scalar_one_or_none()
    if s is None:
        raise not_found("مجموعه مرجع یافت نشد.")
    return s


def create_set(db: Session, tenant_id, actor: Actor, data: dict, request=None,
               correlation_id: str | None = None) -> dict:
    ownership_svc.check_edit_allowed(db, tenant_id, actor, "reference_set", "general")
    dup = db.execute(select(ReferenceSet).where(
        ReferenceSet.tenant_id == tenant_id, ReferenceSet.code == data["code"])).scalar_one_or_none()
    if dup is not None:
        raise conflict("SET_DUPLICATE", "کد مجموعه مرجع تکراری است.")
    s = ReferenceSet(tenant_id=tenant_id, code=data["code"].strip(), title=data["title"].strip(),
                     description=data.get("description"), version=1,
                     owner_installation_id=data.get("owner_installation_id"))
    db.add(s)
    db.flush()
    record_audit(db, tenant_id, actor, "reference_set.create", "reference_set", str(s.id), None,
                 _set_out(s), request=request, correlation_id=correlation_id)
    return _set_out(s)


def list_sets(db: Session, tenant_id) -> list[dict]:
    rows = list(db.execute(select(ReferenceSet).where(
        ReferenceSet.tenant_id == tenant_id).order_by(ReferenceSet.code)).scalars().all())
    return [_set_out(s) for s in rows]


def list_items(db: Session, tenant_id, code: str, include_retired: bool = True) -> list[dict]:
    s = get_set(db, tenant_id, code)
    stmt = select(ReferenceItem).where(ReferenceItem.tenant_id == tenant_id, ReferenceItem.set_id == s.id)
    if not include_retired:
        stmt = stmt.where(ReferenceItem.status == "active")
    rows = list(db.execute(stmt.order_by(ReferenceItem.sort_order, ReferenceItem.code)).scalars().all())
    return [_item_out(i) for i in rows]


def create_item(db: Session, tenant_id, actor: Actor, set_code: str, data: dict, request=None,
                correlation_id: str | None = None) -> dict:
    s = get_set(db, tenant_id, set_code)
    ownership_svc.check_edit_allowed(db, tenant_id, actor, "reference_set", "general")
    dup = db.execute(select(ReferenceItem).where(
        ReferenceItem.tenant_id == tenant_id, ReferenceItem.set_id == s.id,
        ReferenceItem.code == data["code"])).scalar_one_or_none()
    if dup is not None:
        raise conflict("ITEM_DUPLICATE", "کد در این مجموعه تکراری است.")
    if data.get("parent_id"):
        parent = db.execute(select(ReferenceItem).where(
            ReferenceItem.tenant_id == tenant_id, ReferenceItem.id == data["parent_id"],
            ReferenceItem.set_id == s.id)).scalar_one_or_none()
        if parent is None:
            raise not_found("والد موردنظر در همین مجموعه یافت نشد.")
    item = ReferenceItem(
        tenant_id=tenant_id, set_id=s.id, parent_id=data.get("parent_id"),
        code=data["code"].strip(), title=data["title"].strip(),
        sort_order=data.get("sort_order", 0), status="active",
        valid_from=data.get("valid_from"), valid_to=data.get("valid_to"),
    )
    db.add(item)
    s.version += 1  # نسخه‌بندی مجموعه با هر تغییر آیتم
    db.flush()
    event = build_event(EventType.REFERENCE_ITEM_UPDATED, tenant_id, "reference_item", item.id, s.version,
                        {"setCode": s.code, "operation": "created", "code": item.code, "title": item.title},
                        correlation_id)
    record_change(db, tenant_id, "reference_item", item.id, s.version, "create",
                  ["code", "title"], _item_out(item), actor, events=[event])
    record_audit(db, tenant_id, actor, "reference_item.create", "reference_item", str(item.id), None,
                 _item_out(item), request=request, correlation_id=correlation_id)
    return _item_out(item)


def update_item(db: Session, tenant_id, actor: Actor, set_code: str, item_id, data: dict,
                request=None, correlation_id: str | None = None) -> dict:
    s = get_set(db, tenant_id, set_code)
    ownership_svc.check_edit_allowed(db, tenant_id, actor, "reference_set", "general")
    item = db.execute(select(ReferenceItem).where(
        ReferenceItem.tenant_id == tenant_id, ReferenceItem.id == item_id,
        ReferenceItem.set_id == s.id)).scalar_one_or_none()
    if item is None:
        raise not_found("آیتم موردنظر یافت نشد.")
    before = _item_out(item)
    changed = []
    for k in ("title", "sort_order", "status", "valid_from", "valid_to"):
        if k in data and data[k] is not None and data[k] != getattr(item, k):
            setattr(item, k, data[k])
            changed.append(k)
    if not changed:
        return _item_out(item)
    s.version += 1
    db.flush()
    event = build_event(EventType.REFERENCE_ITEM_UPDATED, tenant_id, "reference_item", item.id, s.version,
                        {"setCode": s.code, "operation": "updated", "changedFields": changed,
                         **{k: getattr(item, k) for k in changed}}, correlation_id)
    record_change(db, tenant_id, "reference_item", item.id, s.version, "update", changed,
                  {"changedFields": changed, "setCode": s.code}, actor, events=[event])
    record_audit(db, tenant_id, actor, "reference_item.update", "reference_item", str(item.id), before,
                 _item_out(item), request=request, correlation_id=correlation_id)
    return _item_out(item)
