"""منطق درخواست اصلاح داده (FR-09) — هسته فقط وضعیت درخواست را مدیریت و پس از تأیید اعمال می‌کند."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.common.events import record_audit
from app.core.errors import conflict, not_found
from app.core.security import Actor
from app.modules.change_requests.models import ChangeRequest
from app.modules.persons.models import Person
from app.modules.persons import service as persons_svc

APPLYABLE_FIELDS = ("given_name", "family_name", "display_name")


def create_request(db: Session, tenant_id, actor: Actor, data: dict, request=None,
                   correlation_id: str | None = None) -> dict:
    if data["entity_type"] != "person":
        raise conflict("UNSUPPORTED_ENTITY_TYPE", "در فاز MVP، درخواست اصلاح فقط برای «شخص» پشتیبانی می‌شود.")
    person = db.execute(select(Person).where(
        Person.tenant_id == tenant_id, Person.id == data["entity_id"])).scalar_one_or_none()
    if person is None:
        raise not_found("شخص هدف درخواست یافت نشد.")
    bad = [k for k in data["proposed_changes"] if k not in APPLYABLE_FIELDS]
    if bad:
        raise conflict("FIELD_NOT_REQUESTABLE",
                       "فیلدهای زیر در دامنه درخواست اصلاح نیستند و باید به مرجع مالک هدایت شوند.",
                       {"fields": bad})
    open_dup = db.execute(select(ChangeRequest).where(
        ChangeRequest.tenant_id == tenant_id, ChangeRequest.entity_id == data["entity_id"],
        ChangeRequest.status == "open")).scalars().all()
    for req in open_dup:
        if req.proposed_changes == data["proposed_changes"]:
            raise conflict("REQUEST_ALREADY_OPEN", "درخواست اصلاح یکسانی برای این شخص در جریان است.",
                           {"change_request_id": str(req.id)})
    cr = ChangeRequest(
        tenant_id=tenant_id, entity_type="person", entity_id=data["entity_id"],
        proposed_changes=data["proposed_changes"], reason=data["reason"],
        requested_by=actor.audit_id(), requested_by_name=actor.name,
    )
    db.add(cr)
    db.flush()
    record_audit(db, tenant_id, actor, "change_request.create", "change_request", str(cr.id), None,
                 {"entity_id": str(cr.entity_id), "proposed_changes": cr.proposed_changes},
                 request=request, correlation_id=correlation_id)
    return _cr_out(cr)


def _cr_out(cr: ChangeRequest) -> dict:
    return {
        "id": str(cr.id), "entity_type": cr.entity_type, "entity_id": str(cr.entity_id),
        "proposed_changes": cr.proposed_changes, "reason": cr.reason,
        "requested_by": cr.requested_by, "requested_by_name": cr.requested_by_name,
        "status": cr.status, "decided_by": cr.decided_by, "decided_at": cr.decided_at,
        "decision_note": cr.decision_note, "applied_version": cr.applied_version,
        "created_at": cr.created_at.isoformat(),
    }


def list_requests(db: Session, tenant_id, status: str | None, limit: int, offset: int) -> dict:
    stmt = select(ChangeRequest).where(ChangeRequest.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(ChangeRequest.status == status)
    rows = list(db.execute(stmt.order_by(ChangeRequest.created_at.desc())
                           .limit(limit).offset(offset)).scalars().all())
    return {"items": [_cr_out(r) for r in rows]}


def decide_request(db: Session, tenant_id, actor: Actor, cr_id, action: str, note: str | None,
                   request=None) -> dict:
    """تصمیم متولی داده: approve → اعمال تغییر با کنترل نسخه؛ reject → بستن پرونده."""
    cr = db.execute(select(ChangeRequest).where(
        ChangeRequest.tenant_id == tenant_id, ChangeRequest.id == cr_id)).scalar_one_or_none()
    if cr is None:
        raise not_found("درخواست اصلاح یافت نشد.")
    if cr.status != "open":
        raise conflict("REQUEST_NOT_OPEN", "این درخواست قبلاً تصمیم‌گیری شده است.")
    if action not in ("approve", "reject", "cancel"):
        raise conflict("INVALID_ACTION", "اقدام معتبر نیست.")
    if action == "approve":
        person = db.execute(select(Person).where(
            Person.tenant_id == tenant_id, Person.id == cr.entity_id)).scalar_one_or_none()
        if person is None:
            raise not_found("شخص هدف دیگر موجود نیست.")
        # اعمال توسط متولی داده — bypass مالکیت (تصمیم انسانی متولی)
        updated = persons_svc.update_person(
            db, tenant_id, actor, cr.entity_id, dict(cr.proposed_changes), person.version,
            request=request, bypass_ownership=True,
            correlation_id=f"change-request:{cr.id}",
        )
        cr.applied_version = updated["version"]
        cr.status = "approved"
    elif action == "cancel":
        cr.status = "cancelled"
    else:
        cr.status = "rejected"
    cr.decided_by = actor.audit_id()
    cr.decided_at = utcnow().isoformat()
    cr.decision_note = note
    db.flush()
    record_audit(db, tenant_id, actor, f"change_request.{action}", "change_request", str(cr.id),
                 {"status": "open"}, {"status": cr.status, "note": note}, request=request)
    return _cr_out(cr)
