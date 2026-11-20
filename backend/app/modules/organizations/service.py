"""منطق ساختار سازمانی مشترک (FR-05) — چرخه در ساختار ممنوع است."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.events import EventType, build_event, record_audit, record_change
from app.core.errors import conflict, not_found, version_conflict
from app.core.security import Actor
from app.modules.organizations.models import Organization
from app.modules.ownership import service as ownership_svc


def _org_out(o: Organization) -> dict:
    return {"id": str(o.id), "parent_id": str(o.parent_id) if o.parent_id else None,
            "type": o.type, "code": o.code, "name": o.name, "sort_order": o.sort_order,
            "status": o.status, "version": o.version,
            "created_at": o.created_at.isoformat(), "updated_at": o.updated_at.isoformat()}


def get_org(db: Session, tenant_id, org_id) -> Organization:
    org = db.execute(select(Organization).where(
        Organization.tenant_id == tenant_id, Organization.id == org_id)).scalar_one_or_none()
    if org is None:
        raise not_found("سازمان موردنظر یافت نشد.")
    return org


def _ensure_same_tenant_parent(db: Session, tenant_id, parent_id) -> None:
    pid = uuid.UUID(str(parent_id))
    db.execute(select(Organization).where(
        Organization.tenant_id == tenant_id, Organization.id == pid)).scalar_one_or_none() or not_found(
        "سازمان والد یافت نشد.")


def _would_cycle(db: Session, tenant_id, node_id, new_parent_id) -> bool:
    seen = set()
    cur = uuid.UUID(str(new_parent_id))
    while cur is not None and str(cur) not in seen:
        seen.add(str(cur))
        if str(cur) == str(node_id):
            return True
        parent = db.execute(select(Organization.parent_id).where(
            Organization.tenant_id == tenant_id, Organization.id == cur)).scalar_one_or_none()
        cur = parent
    return False


def create_org(db: Session, tenant_id, actor: Actor, data: dict, request=None,
               correlation_id: str | None = None) -> dict:
    ownership_svc.check_edit_allowed(db, tenant_id, actor, "organization", "general")
    dup = db.execute(select(Organization).where(
        Organization.tenant_id == tenant_id, Organization.type == data["type"],
        Organization.code == data["code"])).scalar_one_or_none()
    if dup is not None:
        raise conflict("ORG_DUPLICATE", "کد سازمان با همین نوع قبلاً ثبت شده است.")
    if data.get("parent_id"):
        _ensure_same_tenant_parent(db, tenant_id, data["parent_id"])
    parent_uuid = uuid.UUID(str(data["parent_id"])) if data.get("parent_id") else None
    org = Organization(
        tenant_id=tenant_id, parent_id=parent_uuid, type=data["type"],
        code=data["code"].strip(), name=data["name"].strip(), sort_order=data.get("sort_order", 0),
        version=1, updated_by=actor.audit_id(),
    )
    db.add(org)
    db.flush()
    event = build_event(EventType.ORGANIZATION_UPDATED, tenant_id, "organization", org.id, org.version,
                        {"operation": "created", "name": org.name, "type": org.type,
                         "code": org.code, "parentId": str(org.parent_id) if org.parent_id else None},
                        correlation_id)
    record_change(db, tenant_id, "organization", org.id, org.version, "create",
                  ["name", "type", "code"], _org_out(org), actor, events=[event])
    record_audit(db, tenant_id, actor, "organization.create", "organization", str(org.id), None,
                 _org_out(org), request=request, correlation_id=correlation_id)
    return _org_out(org)


def update_org(db: Session, tenant_id, actor: Actor, org_id, data: dict, expected_version: int,
               request=None, correlation_id: str | None = None) -> dict:
    org = get_org(db, tenant_id, org_id)
    ownership_svc.check_edit_allowed(db, tenant_id, actor, "organization", "general")
    before = _org_out(org)
    if data.get("parent_id") is not None:
        if str(data["parent_id"]) == str(org.id):
            raise conflict("ORG_CYCLE", "جابه‌جایی سازمان زیر خودش مجاز نیست.")
        _ensure_same_tenant_parent(db, tenant_id, data["parent_id"])
        if _would_cycle(db, tenant_id, org.id, data["parent_id"]):
            raise conflict("ORG_CYCLE", "این جابه‌جایی چرخه در ساختار سازمانی ایجاد می‌کند.")
    changed = [k for k in ("name", "sort_order", "status", "parent_id")
               if k in data and data[k] is not None and data[k] != getattr(org, k)]
    if not changed:
        return _org_out(org)
    from sqlalchemy import update
    res = db.execute(
        update(Organization)
        .where(Organization.id == org.id, Organization.tenant_id == tenant_id,
               Organization.version == expected_version)
        .values(**{k: data[k] for k in changed}, version=org.version + 1, updated_by=actor.audit_id())
    )
    if res.rowcount == 0:
        raise version_conflict(current_version=org.version)
    db.flush()
    db.refresh(org)
    event = build_event(EventType.ORGANIZATION_UPDATED, tenant_id, "organization", org.id, org.version,
                        {"operation": "updated", "changedFields": changed, **{k: getattr(org, k) for k in changed}},
                        correlation_id)
    record_change(db, tenant_id, "organization", org.id, org.version, "update", changed,
                  {"changedFields": changed}, actor, events=[event])
    record_audit(db, tenant_id, actor, "organization.update", "organization", str(org.id), before,
                 _org_out(org), request=request, correlation_id=correlation_id)
    return _org_out(org)


def list_tree(db: Session, tenant_id) -> list[dict]:
    rows = list(db.execute(select(Organization).where(
        Organization.tenant_id == tenant_id).order_by(Organization.sort_order, Organization.name)).scalars().all())
    return [_org_out(o) for o in rows]
