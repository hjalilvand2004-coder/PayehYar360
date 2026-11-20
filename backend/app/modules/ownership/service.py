"""منطق مالکیت داده و کنترل ویرایش (FR-07, FR-08).

گروه‌های فیلد هر موجودیت + سیاست‌های پیش‌فرض هر مشتری.
کنترل واقعی در Backend انجام می‌شود؛ نمایش فقط‌خواندنی در فرانت صرفاً تسهیل است.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.events import record_audit
from app.core.errors import forbidden, not_found
from app.core.security import Actor
from app.modules.ownership.models import OwnershipPolicy

# گروه‌بندی فیلدهای قابل ویرایش به تفکیک موجودیت
FIELD_GROUPS: dict[str, dict[str, list[str]]] = {
    "person": {
        "general": ["given_name", "family_name", "display_name"],
        "identifiers": ["type", "issuer", "value", "verification_status"],
        "contacts": ["type", "value"],
        "status": ["status", "deactivation"],
    },
    "organization": {"general": ["name", "sort_order", "parent_id", "type", "code", "status"]},
    "reference_set": {"general": ["title", "description", "status", "items"]},
}

DEFAULT_POLICIES: list[tuple[str, str, str, str]] = [
    # (entity_type, field_group, owner_type, owner_code)
    ("person", "general", "role", "master_data_editor"),
    ("person", "identifiers", "role", "steward"),
    ("person", "contacts", "role", "master_data_editor"),
    ("person", "status", "role", "steward"),
    ("organization", "general", "role", "master_data_editor"),
    ("reference_set", "general", "role", "master_data_editor"),
]


def seed_default_policies(db: Session, tenant_id, actor: Actor | None = None) -> None:
    for entity_type, group, owner_type, owner_code in DEFAULT_POLICIES:
        exists = db.execute(
            select(OwnershipPolicy).where(
                OwnershipPolicy.tenant_id == tenant_id,
                OwnershipPolicy.entity_type == entity_type,
                OwnershipPolicy.field_group == group,
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(OwnershipPolicy(
                tenant_id=tenant_id, entity_type=entity_type, field_group=group,
                owner_type=owner_type, owner_code=owner_code,
                updated_by=actor.audit_id() if actor else "seed",
            ))


def field_group_of(entity_type: str, field: str) -> str | None:
    for group, fields in FIELD_GROUPS.get(entity_type, {}).items():
        if field in fields:
            return group
    return None


def _actor_matches_policy(actor: Actor, policy: OwnershipPolicy) -> bool:
    if actor.kind == "service":
        # سرویس مرجع: مطابقت owner_code با شناسه سرویس یا scope مالکیت
        if policy.owner_type == "service" and actor.client_id and policy.owner_code == actor.client_id:
            return True
        if policy.owner_type in ("service", "installation") and actor.has_scope(f"owner:{policy.entity_type}"):
            return True
        return False
    # کاربر: نقش اعلامی در سیاست + نقش‌های متولی (steward/tenant_admin) همه‌جا مجازند
    if actor.has_role("steward", "tenant_admin"):
        return True
    if policy.owner_type == "role":
        return actor.has_role(policy.owner_code)
    return False


def check_edit_allowed(db: Session, tenant_id, actor: Actor, entity_type: str, field_group: str) -> None:
    if field_group is None:
        raise forbidden("DATA_OWNER_MISMATCH", "فیلد ارسالی در هیچ گروه مالکیت شناخته‌شده‌ای نیست؛ ویرایش مجاز نیست.")
    policy = db.execute(
        select(OwnershipPolicy).where(
            OwnershipPolicy.tenant_id == tenant_id,
            OwnershipPolicy.entity_type == entity_type,
            OwnershipPolicy.field_group == field_group,
            OwnershipPolicy.status == "active",
        )
    ).scalar_one_or_none()
    if policy is None:
        policy_stub = OwnershipPolicy(entity_type=entity_type, field_group=field_group,
                                      owner_type="role", owner_code="master_data_editor")
        if not _actor_matches_policy(actor, policy_stub):
            raise forbidden(
                "DATA_OWNER_MISMATCH", "ویرایش این داده فقط توسط مرجع معتبر مجاز است.",
                {"entity_type": entity_type, "field_group": field_group},
            )
        return
    if not _actor_matches_policy(actor, policy):
        raise forbidden(
            "DATA_OWNER_MISMATCH", "ویرایش این داده فقط توسط مرجع معتبر مجاز است.",
            {"entity_type": entity_type, "field_group": field_group,
             "owner_type": policy.owner_type, "owner_code": policy.owner_code},
        )


def list_policies(db: Session, tenant_id) -> list[OwnershipPolicy]:
    return list(db.execute(
        select(OwnershipPolicy).where(OwnershipPolicy.tenant_id == tenant_id)
        .order_by(OwnershipPolicy.entity_type, OwnershipPolicy.field_group)
    ).scalars().all())


def upsert_policy(db: Session, tenant_id, actor: Actor, entity_type: str, field_group: str,
                  owner_type: str, owner_code: str, request=None) -> OwnershipPolicy:
    policy = db.execute(
        select(OwnershipPolicy).where(
            OwnershipPolicy.tenant_id == tenant_id,
            OwnershipPolicy.entity_type == entity_type,
            OwnershipPolicy.field_group == field_group,
        )
    ).scalar_one_or_none()
    before = None
    if policy is None:
        policy = OwnershipPolicy(tenant_id=tenant_id, entity_type=entity_type, field_group=field_group)
        db.add(policy)
    else:
        before = {"owner_type": policy.owner_type, "owner_code": policy.owner_code,
                  "version": policy.version}
        policy.version += 1
    policy.owner_type = owner_type
    policy.owner_code = owner_code
    policy.updated_by = actor.audit_id()
    # تغییر مالکیت، عملیات مدیریتی حساس است — ممیزی کامل
    record_audit(db, tenant_id, actor, "ownership.upsert", "ownership_policy",
                 f"{entity_type}:{field_group}", before,
                 {"owner_type": owner_type, "owner_code": owner_code, "version": policy.version},
                 request=request)
    return policy
