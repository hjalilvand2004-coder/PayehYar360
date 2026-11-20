"""منطق کسب‌وکار اشخاص (FR-01..FR-04) — قواعد در service، نه در router."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import statuses
from app.common.crypto import encrypt_value, mask_value, search_hash
from app.common.events import EventType, build_event, record_audit, record_change
from app.core.errors import conflict, forbidden, not_found, version_conflict
from app.core.security import Actor
from app.modules.identities.models import ExternalIdMapping, IdentityAccountLink
from app.modules.ownership import service as ownership_svc
from app.modules.persons.models import Person, PersonContact, PersonIdentifier
from app.modules.persons.repository import (
    get_person, list_contacts, list_identifiers, list_person_history, list_persons, search_by_identifier_hash,
)

GENERAL_FIELDS = ("given_name", "family_name", "display_name")


def _ensure_edit_allowed(db: Session, tenant_id, actor: Actor, entity_type: str, fields: list[str]) -> None:
    groups = {ownership_svc.field_group_of(entity_type, f) for f in fields}
    for group in groups:
        ownership_svc.check_edit_allowed(db, tenant_id, actor, entity_type, group)


def _person_out(p: Person) -> dict:
    return {
        "id": str(p.id), "given_name": p.given_name, "family_name": p.family_name,
        "display_name": p.display_name, "status": p.status, "version": p.version,
        "merged_into_id": str(p.merged_into_id) if p.merged_into_id else None,
        "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(),
    }


def _identifier_out(i: PersonIdentifier) -> dict:
    return {
        "id": str(i.id), "type": i.type, "issuer": i.issuer, "value_masked": i.value_masked,
        "verification_status": i.verification_status, "status": i.status,
        "created_at": i.created_at.isoformat(),
    }


def _contact_out(c: PersonContact) -> dict:
    return {"id": str(c.id), "type": c.type, "value": c.value,
            "verified_at": c.verified_at, "status": c.status}


def person_detail(db: Session, tenant_id, person_id) -> dict:
    p = get_person(db, tenant_id, person_id)
    if p is None:
        raise not_found()
    from app.modules.identities.repository import list_person_links, list_person_mappings
    return {
        **_person_out(p),
        "identifiers": [_identifier_out(i) for i in list_identifiers(db, tenant_id, p.id)],
        "contacts": [_contact_out(c) for c in list_contacts(db, tenant_id, p.id)],
        "account_links": [{
            "id": str(l.id), "issuer": l.issuer, "subject": l.subject, "account_label": l.account_label,
            "status": l.status, "linked_at": l.linked_at,
        } for l in list_person_links(db, tenant_id, p.id)],
        "mappings": [{
            "id": str(m.id), "installation_id": str(m.installation_id),
            "installation_code": code_by_installation(db, tenant_id, m.installation_id),
            "entity_type": m.entity_type, "local_id": m.local_id,
            "entity_id": str(m.entity_id), "status": m.status,
        } for m in list_person_mappings(db, tenant_id, p.id)],
    }


def code_by_installation(db: Session, tenant_id, installation_id) -> str | None:
    from app.modules.integrations.models import SystemInstallation
    inst = db.execute(select(SystemInstallation).where(
        SystemInstallation.tenant_id == tenant_id, SystemInstallation.id == installation_id
    )).scalar_one_or_none()
    return inst.installation_code if inst else None


def create_person(db: Session, tenant_id, actor: Actor, data: dict, request=None,
                  correlation_id: str | None = None) -> dict:
    _ensure_edit_allowed(db, tenant_id, actor, "person", ["given_name"])
    display = data.get("display_name") or f"{data['given_name']} {data['family_name']}".strip()
    person = Person(
        tenant_id=tenant_id, given_name=data["given_name"].strip(), family_name=data["family_name"].strip(),
        display_name=display, status=statuses.PERSON_ACTIVE, version=1,
        created_by=actor.audit_id(), updated_by=actor.audit_id(),
    )
    db.add(person)
    db.flush()

    for idn in data.get("identifiers", []):
        _add_identifier(db, tenant_id, person, actor, idn["type"], idn["issuer"], idn["value"],
                        idn.get("verification_status", "unverified"), skip_ownership=True)
    for con in data.get("contacts", []):
        _add_contact(db, tenant_id, person, actor, con["type"], con["value"], skip_ownership=True)

    db.flush()
    event = build_event(EventType.PERSON_CREATED, tenant_id, "person", person.id, person.version,
                        {"display_name": person.display_name,
                         "given_name": person.given_name, "family_name": person.family_name},
                        correlation_id)
    record_change(db, tenant_id, "person", person.id, person.version, "create",
                  ["given_name", "family_name", "display_name"],
                  {k: person.__dict__[k] for k in GENERAL_FIELDS}, actor, events=[event])
    record_audit(db, tenant_id, actor, "person.create", "person", str(person.id), None,
                 _person_out(person), request=request, correlation_id=correlation_id)
    return _person_out(person)


def update_person(db: Session, tenant_id, actor: Actor, person_id, changes: dict,
                  expected_version: int, request=None, correlation_id: str | None = None,
                  bypass_ownership: bool = False) -> dict:
    person = get_person(db, tenant_id, person_id)
    if person is None:
        raise not_found()
    if person.status != statuses.PERSON_ACTIVE:
        raise conflict("PERSON_NOT_ACTIVE", "شخص فعال نیست؛ اصلاح فقط برای اشخاص فعال مجاز است.")

    if not bypass_ownership:
        _ensure_edit_allowed(db, tenant_id, actor, "person", list(changes.keys()))

    before = _person_out(person)
    changed_fields = [k for k, v in changes.items() if v is not None and v != getattr(person, k)]
    if not changed_fields:
        return _person_out(person)  # بدون تغییر نسخه

    # کنترل نسخه در شرط UPDATE (بند ۸.۲) — صرفاً در فرانت کافی نیست
    values = {k: v.strip() for k, v in changes.items() if k in GENERAL_FIELDS and v is not None}
    values["version"] = person.version + 1
    values["updated_by"] = actor.audit_id()
    if "given_name" in values or "family_name" in values:
        if "display_name" not in values:
            values["display_name"] = f"{values.get('given_name', person.given_name)} {values.get('family_name', person.family_name)}".strip()
    from sqlalchemy import update
    res = db.execute(
        update(Person)
        .where(Person.id == person.id, Person.tenant_id == tenant_id, Person.version == expected_version)
        .values(**values)
    )
    if res.rowcount == 0:
        raise version_conflict(current_version=person.version)
    db.flush()
    db.refresh(person)

    payload = {k: getattr(person, k) for k in changed_fields}
    event = build_event(EventType.PERSON_UPDATED, tenant_id, "person", person.id, person.version,
                        {"changedFields": changed_fields, **payload}, correlation_id)
    record_change(db, tenant_id, "person", person.id, person.version, "update", changed_fields,
                  {"changedFields": changed_fields, **payload}, actor, events=[event])
    record_audit(db, tenant_id, actor, "person.update", "person", str(person.id), before,
                 _person_out(person), request=request, correlation_id=correlation_id)
    return _person_out(person)


def deactivate_person(db: Session, tenant_id, actor: Actor, person_id, expected_version: int,
                      reason: str | None = None, request=None, correlation_id: str | None = None) -> dict:
    person = get_person(db, tenant_id, person_id)
    if person is None:
        raise not_found()
    if person.status != statuses.PERSON_ACTIVE:
        raise conflict("PERSON_NOT_ACTIVE", "شخص قبلاً غیرفعال یا ادغام شده است.")
    ownership_svc.check_edit_allowed(db, tenant_id, actor, "person", "status")

    from sqlalchemy import update
    from app.common.db import utcnow
    res = db.execute(
        update(Person)
        .where(Person.id == person.id, Person.tenant_id == tenant_id, Person.version == expected_version)
        .values(status=statuses.PERSON_INACTIVE, deactivated_at=utcnow().isoformat(),
                version=person.version + 1, updated_by=actor.audit_id())
    )
    if res.rowcount == 0:
        raise version_conflict(current_version=person.version)
    db.flush()
    db.refresh(person)

    event = build_event(EventType.PERSON_DEACTIVATED, tenant_id, "person", person.id, person.version,
                        {"reason": reason}, correlation_id)
    record_change(db, tenant_id, "person", person.id, person.version, "deactivate", ["status"],
                  {"status": person.status, "reason": reason}, actor, events=[event])
    record_audit(db, tenant_id, actor, "person.deactivate", "person", str(person.id),
                 {"status": "active"}, {"status": "inactive", "reason": reason},
                 request=request, correlation_id=correlation_id)
    return _person_out(person)


def _add_identifier(db: Session, tenant_id, person: Person, actor: Actor, itype: str, issuer: str,
                    value: str, verification: str, skip_ownership: bool = False, request=None,
                    correlation_id: str | None = None) -> PersonIdentifier:
    if not skip_ownership:
        _ensure_edit_allowed(db, tenant_id, actor, "person", ["type"])
    vh = search_hash(value)
    duplicate = db.execute(
        select(PersonIdentifier).where(
            PersonIdentifier.tenant_id == tenant_id, PersonIdentifier.type == itype,
            PersonIdentifier.issuer == issuer, PersonIdentifier.value_hash == vh,
            PersonIdentifier.status == "active",
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise conflict(
            "IDENTIFIER_DUPLICATE",
            "این شناسه با همین نوع و حوزه صادرکننده قبلاً برای شخص دیگری ثبت شده است.",
            {"person_id": str(duplicate.person_id)} if actor.has_role("steward", "tenant_admin") else None,
        )
    ident = PersonIdentifier(
        tenant_id=tenant_id, person_id=person.id, type=itype, issuer=issuer,
        encrypted_value=encrypt_value(value), value_hash=vh, value_masked=mask_value(value),
        verification_status=verification if verification in ("unverified", "verified", "rejected") else "unverified",
        status="active", active_key=f"{itype}:{issuer}:{vh}", created_by=actor.audit_id(),
    )
    db.add(ident)
    db.flush()
    record_audit(db, tenant_id, actor, "person.identifier.add", "person_identifier", str(ident.id),
                 None, {"type": itype, "issuer": issuer, "value_masked": ident.value_masked,
                        "verification_status": ident.verification_status},
                 request=request, correlation_id=correlation_id)
    return ident


def add_identifier(db: Session, tenant_id, actor: Actor, person_id, data: dict, request=None,
                   correlation_id: str | None = None) -> dict:
    person = get_person(db, tenant_id, person_id)
    if person is None:
        raise not_found()
    ident = _add_identifier(db, tenant_id, person, actor, data["type"], data["issuer"],
                            data["value"], data.get("verification_status", "unverified"),
                            request=request, correlation_id=correlation_id)
    return _identifier_out(ident)


def patch_identifier(db: Session, tenant_id, actor: Actor, person_id, identifier_id, data: dict,
                     request=None, correlation_id: str | None = None) -> dict:
    ident = db.execute(select(PersonIdentifier).where(
        PersonIdentifier.tenant_id == tenant_id, PersonIdentifier.id == identifier_id,
        PersonIdentifier.person_id == person_id,
    )).scalar_one_or_none()
    if ident is None:
        raise not_found()
    # تأیید/رد شناسه هویتی، در مالکیت متولی داده است
    _ensure_edit_allowed(db, tenant_id, actor, "person", ["verification_status"] if "verification_status" in data else ["type"])
    before = _identifier_out(ident)
    if data.get("verification_status") in ("verified", "rejected", "unverified"):
        ident.verification_status = data["verification_status"]
    if data.get("status") in ("active", "revoked"):
        ident.status = data["status"]
        ident.active_key = f"{ident.type}:{ident.issuer}:{ident.value_hash}" if ident.status == "active" else None
    db.flush()
    record_audit(db, tenant_id, actor, "person.identifier.patch", "person_identifier", str(ident.id),
                 before, _identifier_out(ident), request=request, correlation_id=correlation_id)
    return _identifier_out(ident)


def _add_contact(db: Session, tenant_id, person: Person, actor: Actor, ctype: str, value: str,
                 skip_ownership: bool = False, request=None, correlation_id: str | None = None) -> PersonContact:
    if not skip_ownership:
        _ensure_edit_allowed(db, tenant_id, actor, "person", ["type"])
    contact = PersonContact(
        tenant_id=tenant_id, person_id=person.id, type=ctype, value=value.strip(),
        value_hash=search_hash(value), status="active",
    )
    db.add(contact)
    db.flush()
    record_audit(db, tenant_id, actor, "person.contact.add", "person_contact", str(contact.id),
                 None, {"type": ctype, "value": value}, request=request, correlation_id=correlation_id)
    return contact


def add_contact(db: Session, tenant_id, actor: Actor, person_id, data: dict, request=None,
                correlation_id: str | None = None) -> dict:
    person = get_person(db, tenant_id, person_id)
    if person is None:
        raise not_found()
    contact = _add_contact(db, tenant_id, person, actor, data["type"], data["value"],
                           request=request, correlation_id=correlation_id)
    return _contact_out(contact)


def patch_contact(db: Session, tenant_id, actor: Actor, person_id, contact_id, data: dict,
                  request=None, correlation_id: str | None = None) -> dict:
    contact = db.execute(select(PersonContact).where(
        PersonContact.tenant_id == tenant_id, PersonContact.id == contact_id,
        PersonContact.person_id == person_id,
    )).scalar_one_or_none()
    if contact is None:
        raise not_found()
    _ensure_edit_allowed(db, tenant_id, actor, "person", ["type"])
    before = _contact_out(contact)
    if data.get("status") in ("active", "revoked"):
        contact.status = data["status"]
    if data.get("verified") is True:
        from app.common.db import utcnow
        contact.verified_at = utcnow().isoformat()
    db.flush()
    record_audit(db, tenant_id, actor, "person.contact.patch", "person_contact", str(contact.id),
                 before, _contact_out(contact), request=request, correlation_id=correlation_id)
    return _contact_out(contact)


def search_persons(db: Session, tenant_id, actor: Actor, q: str | None, status: str | None,
                   identifier_type: str | None, identifier_value: str | None,
                   limit: int, offset: int) -> dict:
    if identifier_value:
        if not identifier_type:
            raise conflict("INVALID_SEARCH", "برای جست‌وجوی شناسه، نوع شناسه نیز لازم است.")
        # جست‌وجوی دقیق شناسه حساس فقط برای نقش‌های مجاز
        if not actor.has_role("steward", "tenant_admin", "master_data_editor") and not (
            actor.kind == "service" and actor.has_scope("read:person")
        ):
            raise forbidden("INSUFFICIENT_ROLE", "جست‌وجوی شناسه ملی فقط برای نقش‌های مجاز امکان‌پذیر است.")
        vh = search_hash(identifier_value)
        person = search_by_identifier_hash(db, tenant_id, identifier_type, vh)
        items = [person] if person else []
        return {"items": [_person_out(p) for p in items], "total": len(items), "limit": limit, "offset": 0}
    items, total = list_persons(db, tenant_id, q, status, limit, offset)
    return {"items": [_person_out(p) for p in items], "total": total, "limit": limit, "offset": offset}


def history(db: Session, tenant_id, person_id) -> list[dict]:
    if get_person(db, tenant_id, person_id) is None:
        raise not_found()
    rows = list_person_history(db, tenant_id, person_id)
    return [{
        "seq": r.seq, "operation": r.operation, "version": r.entity_version,
        "changed_fields": r.changed_fields, "data": r.data, "actor_id": r.actor_id,
        "occurred_at": r.occurred_at,
    } for r in rows]
