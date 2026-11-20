"""دسترسی داده ماژول هویت و نگاشت."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.identities.models import ExternalIdMapping, IdentityAccountLink
from app.modules.integrations.models import SystemInstallation


def list_person_links(db: Session, tenant_id, person_id) -> list[IdentityAccountLink]:
    return list(db.execute(
        select(IdentityAccountLink).where(
            IdentityAccountLink.tenant_id == tenant_id, IdentityAccountLink.person_id == person_id
        ).order_by(IdentityAccountLink.created_at)
    ).scalars().all())


def find_active_link(db: Session, tenant_id, issuer: str, subject: str) -> IdentityAccountLink | None:
    return db.execute(
        select(IdentityAccountLink).where(
            IdentityAccountLink.tenant_id == tenant_id,
            IdentityAccountLink.issuer == issuer,
            IdentityAccountLink.subject == subject,
            IdentityAccountLink.status == "active",
        )
    ).scalar_one_or_none()


def list_person_mappings(db: Session, tenant_id, entity_id) -> list[ExternalIdMapping]:
    return list(db.execute(
        select(ExternalIdMapping).where(
            ExternalIdMapping.tenant_id == tenant_id,
            ExternalIdMapping.entity_id == entity_id,
        ).order_by(ExternalIdMapping.created_at)
    ).scalars().all())


def get_installation(db: Session, tenant_id, installation_ref: str | None, code: str | None = None) -> SystemInstallation | None:
    """جست‌وجو بر اساس شناسه UUID یا کد نصب — ورودی رشته‌ای هم پذیرفته می‌شود."""
    if installation_ref:
        ref_uuid = None
        try:
            ref_uuid = uuid.UUID(str(installation_ref))
        except (ValueError, AttributeError, TypeError):
            ref_uuid = None
        if ref_uuid is not None:
            return db.execute(select(SystemInstallation).where(
                SystemInstallation.tenant_id == tenant_id,
                (SystemInstallation.id == ref_uuid) | (SystemInstallation.installation_code == installation_ref),
            )).scalar_one_or_none()
        return db.execute(select(SystemInstallation).where(
            SystemInstallation.tenant_id == tenant_id,
            SystemInstallation.installation_code == installation_ref,
        )).scalar_one_or_none()
    if code:
        return db.execute(select(SystemInstallation).where(
            SystemInstallation.tenant_id == tenant_id, SystemInstallation.installation_code == code,
        )).scalar_one_or_none()
    return None


def find_mapping(db: Session, tenant_id, installation_id, entity_type: str, local_id: str) -> ExternalIdMapping | None:
    return db.execute(
        select(ExternalIdMapping).where(
            ExternalIdMapping.tenant_id == tenant_id,
            ExternalIdMapping.installation_id == installation_id,
            ExternalIdMapping.entity_type == entity_type,
            ExternalIdMapping.local_id == local_id,
        )
    ).scalar_one_or_none()


def list_mappings(db: Session, tenant_id, installation_code: str | None, entity_type: str | None,
                  entity_id: str | None, limit: int, offset: int) -> list[ExternalIdMapping]:
    stmt = select(ExternalIdMapping).where(ExternalIdMapping.tenant_id == tenant_id)
    if installation_code:
        inst = get_installation(db, tenant_id, None, installation_code)
        if inst is None:
            return []
        stmt = stmt.where(ExternalIdMapping.installation_id == inst.id)
    if entity_type:
        stmt = stmt.where(ExternalIdMapping.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(ExternalIdMapping.entity_id == entity_id)
    stmt = stmt.order_by(ExternalIdMapping.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())
