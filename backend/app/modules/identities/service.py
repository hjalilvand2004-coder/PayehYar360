"""منطق هویت: اتصال حساب SSO به شخص و نگاشت شناسه‌های محلی (FR-03, FR-04)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import statuses
from app.common.events import EventType, build_event, record_audit, record_change
from app.core.errors import conflict, forbidden, not_found
from app.core.security import Actor
from app.modules.identities.models import ExternalIdMapping, EntityRegistry, IdentityAccountLink
from app.modules.identities.repository import find_active_link, find_mapping, get_installation, list_mappings
from app.modules.persons.repository import get_person
from app.core.config import settings


def _require_management_role(actor: Actor):
    if actor.kind == "service":
        if not (actor.has_scope("owner:identity") or actor.has_scope("owner:person")):
            raise forbidden("INSUFFICIENT_SCOPE", "سرویس جاری مجاز به مدیریت اتصال/نگاشت نیست.")
        return
    if not actor.has_role("steward", "integration_admin", "tenant_admin"):
        raise forbidden("INSUFFICIENT_ROLE", "اتصال حساب و نگاشت شناسه فقط توسط نقش‌های مجاز انجام می‌شود.")


def link_account(db: Session, tenant_id, actor: Actor, data: dict, request=None,
                 correlation_id: str | None = None) -> dict:
    """اتصال کنترل‌شده حساب SSO — صرفاً بر اساس issuer+subject، هرگز بر اساس ایمیل."""
    _require_management_role(actor)
    person = get_person(db, tenant_id, data["person_id"])
    if person is None:
        raise not_found()
    if person.status == statuses.PERSON_MERGED:
        raise conflict("PERSON_MERGED", "به شخص ادغام‌شده نمی‌توان حساب متصل کرد؛ شناسه نهایی را استفاده کنید.")
    issuer = (data.get("issuer") or settings.OIDC_ISSUER).strip()
    subject = str(data["subject"]).strip()
    existing = find_active_link(db, tenant_id, issuer, subject)
    if existing is not None:
        if str(existing.person_id) == str(person.id):
            raise conflict("LINK_EXISTS", "این حساب قبلاً به همین شخص متصل شده است.")
        raise conflict(
            "ACCOUNT_ALREADY_LINKED",
            "این حساب قبلاً به شخص دیگری در همین مشتری متصل شده است؛ ابتدا اتصال فعلی را قطع کنید.",
            {"person_id": str(existing.person_id)} if actor.has_role("steward", "tenant_admin", "integration_admin") else None,
        )
    from app.common.db import utcnow
    link = IdentityAccountLink(
        tenant_id=tenant_id, person_id=person.id, issuer=issuer, subject=subject,
        account_label=data.get("account_label"), status=statuses.LINK_ACTIVE, active_key=subject,
        linked_by=actor.audit_id(), linked_at=utcnow().isoformat(),
        note=data.get("note"),
    )
    db.add(link)
    db.flush()
    event = build_event(EventType.IDENTITY_ACCOUNT_LINKED, tenant_id, "identity_link", link.id,
                        1, {"personId": str(person.id), "issuer": issuer, "subject": subject,
                            "status": "active"}, correlation_id)
    record_change(db, tenant_id, "identity_link", link.id, 1, "link", ["status"],
                  {"person_id": str(person.id), "issuer": issuer, "subject": subject}, actor, events=[event])
    record_audit(db, tenant_id, actor, "identity.link_account", "identity_link", str(link.id), None,
                 {"person_id": str(person.id), "issuer": issuer, "subject": subject},
                 request=request, correlation_id=correlation_id)
    return {
        "id": str(link.id), "person_id": str(person.id), "issuer": issuer, "subject": subject,
        "account_label": link.account_label, "status": link.status, "linked_at": link.linked_at,
    }


def revoke_link(db: Session, tenant_id, actor: Actor, link_id, note: str | None, request=None) -> dict:
    _require_management_role(actor)
    link = db.execute(select(IdentityAccountLink).where(
        IdentityAccountLink.tenant_id == tenant_id, IdentityAccountLink.id == link_id
    )).scalar_one_or_none()
    if link is None:
        raise not_found()
    if link.status != statuses.LINK_ACTIVE:
        raise conflict("LINK_NOT_ACTIVE", "اتصال قبلاً قطع شده است.")
    link.status = statuses.LINK_REVOKED
    link.active_key = None
    link.note = note or link.note
    db.flush()
    record_audit(db, tenant_id, actor, "identity.revoke_link", "identity_link", str(link.id),
                 {"status": "active"}, {"status": "revoked", "note": note}, request=request)
    return {"id": str(link.id), "status": link.status}


def resolve_me(db: Session, tenant_id, actor: Actor) -> dict:
    """بازیابی شخص متناظر حساب جاری (GET /identity/me)."""
    if actor.kind == "service":
        return {"kind": "service", "client_id": actor.client_id, "name": actor.name,
                "scopes": sorted(actor.scopes), "person": None}
    link = find_active_link(db, tenant_id, settings.OIDC_ISSUER, actor.subject) or \
        find_active_link(db, tenant_id, actor.issuer or settings.OIDC_ISSUER, actor.subject)
    if link is None:
        return {"kind": "user", "subject": actor.subject, "name": actor.name,
                "roles": sorted(actor.roles), "tenant_codes": actor.tenant_codes, "person": None,
                "linked": False}
    person = get_person(db, tenant_id, link.person_id)
    person_out = None
    if person is not None:
        person_out = {
            "id": str(person.id), "display_name": person.display_name, "status": person.status,
            "version": person.version,
        }
    return {"kind": "user", "subject": actor.subject, "name": actor.name,
            "roles": sorted(actor.roles), "tenant_codes": actor.tenant_codes,
            "person": person_out, "linked": person is not None}


def register_mapping(db: Session, tenant_id, actor: Actor, data: dict, request=None,
                     correlation_id: str | None = None) -> dict:
    """ثبت نگاشت شناسه محلی → شناسه مشترک (FR-03)."""
    if actor.kind == "service":
        if not (actor.has_scope("owner:person") or actor.has_scope("owner:identity") or actor.has_scope("owner:organization")):
            raise forbidden("INSUFFICIENT_SCOPE", "سرویس جاری مجاز به ثبت نگاشت نیست.")
    else:
        if not actor.has_role("steward", "integration_admin", "tenant_admin", "master_data_editor"):
            raise forbidden("INSUFFICIENT_ROLE", "ثبت نگاشت شناسه فقط توسط نقش‌های مجاز انجام می‌شود.")
    inst = get_installation(db, tenant_id, data.get("installation_id"), data.get("installation_code"))
    if inst is None or inst.tenant_id != tenant_id:
        raise not_found("نصب موردنظر یافت نشد.")
    entity_type = data["entity_type"]
    entity_id = data["entity_id"]
    if isinstance(entity_id, str):
        entity_id = uuid.UUID(entity_id)
    _validate_entity_target(db, tenant_id, entity_type, entity_id)
    existing = find_mapping(db, tenant_id, inst.id, entity_type, data["local_id"])
    if existing is not None:
        if str(existing.entity_id) == str(entity_id):
            return _mapping_out(db, tenant_id, existing)  # ثبت مجدد یکسان → بدون اثر
        raise conflict(
            "MAPPING_CONFLICT",
            "این شناسه محلی قبلاً به شناسه دیگری نگاشت شده است.",
            {"entity_id": str(existing.entity_id)},
        )
    mapping = ExternalIdMapping(
        tenant_id=tenant_id, installation_id=inst.id, entity_type=entity_type,
        local_id=str(data["local_id"]), entity_id=entity_id, status="active",
        note=data.get("note"), created_by=actor.audit_id(),
    )
    db.add(mapping)
    db.flush()
    event = build_event(EventType.IDENTIFIER_MAPPING_UPDATED, tenant_id, "id_mapping", mapping.id, 1,
                        {"installation": inst.installation_code, "entityType": entity_type,
                         "localId": str(data["local_id"]), "entityId": str(entity_id),
                         "operation": "registered"}, correlation_id)
    record_change(db, tenant_id, "id_mapping", mapping.id, 1, "mapping", ["status"],
                  {"installation": inst.installation_code, "entity_type": entity_type,
                   "local_id": str(data["local_id"]), "entity_id": str(entity_id)}, actor, events=[event])
    record_audit(db, tenant_id, actor, "identity.mapping.register", "external_id_mapping", str(mapping.id),
                 None, {"installation": inst.installation_code, "entity_type": entity_type,
                        "local_id": str(data["local_id"]), "entity_id": str(entity_id)},
                 request=request, correlation_id=correlation_id)
    return _mapping_out(db, tenant_id, mapping)


def _validate_entity_target(db: Session, tenant_id, entity_type: str, entity_id) -> None:
    from app.modules.organizations.models import Organization
    if entity_type == "person":
        if get_person(db, tenant_id, entity_id) is None:
            raise not_found("شخص هدف نگاشت یافت نشد.")
    elif entity_type == "organization":
        org = db.execute(select(Organization).where(
            Organization.tenant_id == tenant_id, Organization.id == entity_id)).scalar_one_or_none()
        if org is None:
            raise not_found("سازمان هدف نگاشت یافت نشد.")
    elif entity_type == "registry_entity":
        ent = db.execute(select(EntityRegistry).where(
            EntityRegistry.tenant_id == tenant_id, EntityRegistry.id == entity_id)).scalar_one_or_none()
        if ent is None:
            raise not_found("موجودیت ثبت‌شده هدف نگاشت یافت نشد.")
    else:
        raise conflict("UNSUPPORTED_ENTITY_TYPE",
                       "نوع موجودیت پشتیبانی نمی‌شود؛ موجودیت‌های تخصصی از طریق entity_registry معرفی شوند.")


def _mapping_out(db: Session, tenant_id, m: ExternalIdMapping) -> dict:
    inst = get_installation(db, tenant_id, str(m.installation_id))
    return {
        "id": str(m.id), "installation_id": str(m.installation_id),
        "installation_code": inst.installation_code if inst else None,
        "entity_type": m.entity_type, "local_id": m.local_id,
        "entity_id": str(m.entity_id), "status": m.status, "note": m.note,
        "created_at": m.created_at.isoformat(),
    }


def resolve_mapping(db: Session, tenant_id, actor: Actor, data: dict, request=None) -> dict:
    """تبدیل شناسه محلی به شناسه مشترک (POST /id-mappings/resolve)."""
    if actor.kind == "service":
        if not (actor.has_scope("read:person") or actor.has_scope("owner:person") or actor.has_scope("sync")):
            raise forbidden("INSUFFICIENT_SCOPE", "سرویس جاری مجاز به resolve نگاشت نیست.")
    inst = get_installation(db, tenant_id, data.get("installation_id"), data.get("installation_code"))
    if inst is None:
        raise not_found("نصب موردنظر یافت نشد.")
    mapping = find_mapping(db, tenant_id, inst.id, data["entity_type"], str(data["local_id"]))
    if mapping is None or mapping.status != "active":
        raise not_found("MAPPING_NOT_FOUND و نگاشت فعالی برای این شناسه محلی وجود ندارد.")
    result = _mapping_out(db, tenant_id, mapping)
    if mapping.entity_type == "person":
        person = get_person(db, tenant_id, mapping.entity_id)
        if person is not None:
            # پیروی از alias در صورت ادغام — مصرف‌کننده باید شناسه نهایی را استفاده کند
            final = person
            seen = set()
            while final.status == statuses.PERSON_MERGED and final.merged_into_id and str(final.id) not in seen:
                seen.add(str(final.id))
                nxt = get_person(db, tenant_id, final.merged_into_id)
                if nxt is None:
                    break
                final = nxt
            result["entity"] = {
                "id": str(final.id), "display_name": final.display_name,
                "status": final.status, "version": final.version,
            }
            if final.id != person.id:
                result["merged_from"] = str(person.id)
    elif mapping.entity_type == "organization":
        from app.modules.organizations.models import Organization
        org = db.execute(select(Organization).where(
            Organization.tenant_id == tenant_id, Organization.id == mapping.entity_id)).scalar_one_or_none()
        if org is not None:
            result["entity"] = {"id": str(org.id), "name": org.name, "type": org.type,
                                "status": org.status, "version": org.version}
    return result


def search_mappings(db: Session, tenant_id, installation_code: str | None, entity_type: str | None,
                    entity_id: str | None, limit: int, offset: int) -> list[dict]:
    rows = list_mappings(db, tenant_id, installation_code, entity_type, entity_id, limit, offset)
    return [_mapping_out(db, tenant_id, m) for m in rows]
