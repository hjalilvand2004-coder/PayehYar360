"""هسته تراکنش تغییر: تخصیص شماره ترتیبی هر مشتری + ChangeLog + Outbox + Audit در یک تراکنش.

مطابق بند ۹.۴ و ۹.۵ سند فنی:
- شمارنده هر مشتری با قفل ردیف (FOR UPDATE) تخصیص می‌شود تا ترتیب Commit و شماره هم‌راستا بماند.
- رویدادها ابتدا در outbox_events ثبت و سپس توسط Worker منتشر می‌شوند (تحویل حداقل یک‌بار).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.core.security import Actor

SCHEMA_VERSION = 1
SOURCE_SYSTEM = "shared-core"


class EventType:
    PERSON_CREATED = "PersonCreated"
    PERSON_UPDATED = "PersonUpdated"
    PERSON_DEACTIVATED = "PersonDeactivated"
    PERSON_MERGED = "PersonMerged"
    PERSON_MERGE_CORRECTED = "PersonMergeCorrected"
    ORGANIZATION_UPDATED = "OrganizationUpdated"
    REFERENCE_ITEM_UPDATED = "ReferenceItemUpdated"
    IDENTITY_ACCOUNT_LINKED = "IdentityAccountLinked"
    IDENTIFIER_MAPPING_UPDATED = "IdentifierMappingUpdated"
    STUDENT_CREATED = "StudentCreated"
    STUDENT_UPDATED = "StudentUpdated"
    STUDENT_DEACTIVATED = "StudentDeactivated"


def build_event(event_type: str, tenant_id: str, entity_type: str, entity_id: str,
                entity_version: int, payload: dict, correlation_id: str | None) -> dict:
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": event_type,
        "schemaVersion": SCHEMA_VERSION,
        "tenantId": str(tenant_id),
        "sourceSystem": SOURCE_SYSTEM,
        "entityType": entity_type,
        "entityId": str(entity_id),
        "entityVersion": int(entity_version),
        "occurredAt": utcnow().isoformat().replace("+00:00", "Z"),
        "correlationId": correlation_id or str(uuid.uuid4()),
        "payload": payload,
    }


def allocate_seq(session: Session, tenant_id) -> int:
    """تخصیص شماره ترتیبی تغییر با قفل ردیف شمارنده مشتری (بند ۹.۵)."""
    from app.modules.synchronization.models import TenantChangeCounter

    row = session.execute(
        select(TenantChangeCounter).where(TenantChangeCounter.tenant_id == tenant_id).with_for_update()
    ).scalar_one_or_none()
    if row is None:
        row = TenantChangeCounter(tenant_id=tenant_id, last_seq=0)
        session.add(row)
        session.flush()
    row.last_seq = int(row.last_seq) + 1
    return int(row.last_seq)


def record_change(session: Session, tenant_id, entity_type: str, entity_id, entity_version: int,
                  operation: str, changed_fields: list[str], data: dict, actor: Actor,
                  events: list[dict] | None = None) -> int:
    """ثبت ChangeLog + Outbox در تراکنش جاری (بدون commit — تراکنش توسط فراخوان انجام می‌شود)."""
    from app.modules.synchronization.models import ChangeLog, OutboxEvent

    seq = allocate_seq(session, tenant_id)
    session.add(ChangeLog(
        tenant_id=tenant_id, seq=seq, entity_type=entity_type, entity_id=str(entity_id),
        entity_version=entity_version, operation=operation, changed_fields=changed_fields,
        data=data, actor_id=actor.audit_id(), occurred_at=utcnow(),
    ))
    for event in (events or []):
        session.add(OutboxEvent(
            id=uuid.UUID(event["eventId"]), tenant_id=tenant_id,
            event_type=event["eventType"], entity_type=entity_type, entity_id=str(entity_id),
            payload=event, status="pending", attempts=0,
        ))
    return seq


def record_audit(session: Session, tenant_id, actor: Actor, operation: str, entity_type: str,
                 entity_id: str | None, before: dict | None, after: dict | None,
                 request=None, correlation_id: str | None = None, note: str | None = None) -> None:
    from app.modules.audit.models import AuditLog

    session.add(AuditLog(
        tenant_id=tenant_id,
        actor_type=actor.kind, actor_id=actor.audit_id(), actor_name=actor.name, actor_roles=sorted(actor.roles),
        operation=operation, entity_type=entity_type, entity_id=str(entity_id) if entity_id else None,
        before=json.dumps(before, ensure_ascii=False, default=str) if before else None,
        after=json.dumps(after, ensure_ascii=False, default=str) if after else None,
        ip=(request.client.host if request and request.client else None),
        user_agent=(request.headers.get("user-agent") if request else None),
        correlation_id=correlation_id, note=note,
    ))
