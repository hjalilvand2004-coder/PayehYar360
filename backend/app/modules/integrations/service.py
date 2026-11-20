"""منطق مشتری‌ها، نصب‌ها و پایش اتصال (FR-15, FR-17)."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import statuses
from app.common.db import utcnow
from app.common.events import record_audit
from app.core.errors import conflict, not_found
from app.core.security import Actor
from app.modules.integrations.models import SystemInstallation, Tenant
from app.modules.ownership.service import seed_default_policies
from app.modules.persons.models import Person
from app.modules.synchronization.models import OutboxEvent, SnapshotJob, SyncCheckpoint, TenantChangeCounter
from app.modules.change_requests.models import ChangeRequest
from app.modules.data_quality.models import ResolutionCase


def create_tenant(db: Session, actor: Actor, data: dict, request=None) -> Tenant:
    """ایجاد مشتری + شمارنده ترتیب + سیاست‌های پیش‌فرض مالکیت."""
    code = data["code"].strip().lower()
    dup = db.execute(select(Tenant).where(Tenant.code == code)).scalar_one_or_none()
    if dup is not None:
        raise conflict("TENANT_DUPLICATE", "کد مشتری تکراری است.")
    tenant = Tenant(code=code, name=data["name"].strip(), status="active", note=data.get("note"))
    db.add(tenant)
    db.flush()
    db.add(TenantChangeCounter(tenant_id=tenant.id, last_seq=0))
    seed_default_policies(db, tenant.id, actor)
    record_audit(db, tenant.id, actor, "tenant.create", "tenant", str(tenant.id), None,
                 {"code": tenant.code, "name": tenant.name}, request=request)
    return tenant


def list_tenants(db: Session) -> list[Tenant]:
    return list(db.execute(select(Tenant).order_by(Tenant.code)).scalars().all())


def _inst_out(inst: SystemInstallation) -> dict:
    return {
        "id": str(inst.id), "tenant_id": str(inst.tenant_id), "system_code": inst.system_code,
        "installation_code": inst.installation_code, "title": inst.title, "mode": inst.mode,
        "status": inst.status, "base_url": inst.base_url, "owner_scopes": inst.owner_scopes,
        "last_seen_at": inst.last_seen_at, "note": inst.note,
        "created_at": inst.created_at.isoformat(),
    }


def list_installations(db: Session, tenant_id) -> list[SystemInstallation]:
    return list(db.execute(select(SystemInstallation).where(
        SystemInstallation.tenant_id == tenant_id).order_by(SystemInstallation.installation_code)).scalars().all())


def create_installation(db: Session, tenant_id, actor: Actor, data: dict, request=None) -> SystemInstallation:
    dup = db.execute(select(SystemInstallation).where(
        SystemInstallation.tenant_id == tenant_id,
        SystemInstallation.installation_code == data["installation_code"])).scalar_one_or_none()
    if dup is not None:
        raise conflict("INSTALLATION_DUPLICATE", "کد نصب در این مشتری تکراری است.")
    inst = SystemInstallation(
        tenant_id=tenant_id, system_code=data["system_code"], installation_code=data["installation_code"],
        title=data["title"], mode=data.get("mode", "integrated"), status="active",
        base_url=data.get("base_url"), owner_scopes=data.get("owner_scopes"), note=data.get("note"),
    )
    db.add(inst)
    db.flush()
    record_audit(db, tenant_id, actor, "installation.create", "system_installation", str(inst.id),
                 None, _inst_out(inst), request=request)
    return inst


def update_installation(db: Session, tenant_id, actor: Actor, inst_id, data: dict, request=None) -> SystemInstallation:
    inst = db.execute(select(SystemInstallation).where(
        SystemInstallation.tenant_id == tenant_id, SystemInstallation.id == inst_id)).scalar_one_or_none()
    if inst is None:
        raise not_found("نصب موردنظر یافت نشد.")
    before = _inst_out(inst)
    for k in ("title", "mode", "status", "base_url", "owner_scopes", "note"):
        if k in data and data[k] is not None:
            setattr(inst, k, data[k])
    record_audit(db, tenant_id, actor, "installation.update", "system_installation", str(inst.id),
                 before, _inst_out(inst), request=request)
    return inst


def mark_seen(db: Session, tenant_id, installation_ref: str) -> None:
    inst = db.execute(select(SystemInstallation).where(
        SystemInstallation.tenant_id == tenant_id,
        SystemInstallation.installation_code == installation_ref)).scalar_one_or_none()
    if inst is not None:
        inst.last_seen_at = utcnow().isoformat()


def outbox_stats(db: Session) -> dict:
    pending_count = db.execute(select(func.count()).where(OutboxEvent.status == "pending")).scalar_one()
    oldest = db.execute(select(func.min(OutboxEvent.created_at)).where(
        OutboxEvent.status == "pending")).scalar_one()
    age_seconds = None
    if oldest:
        try:
            from datetime import datetime, timezone
            oldest_dt = datetime.fromisoformat(str(oldest))
            if oldest_dt.tzinfo is None:
                oldest_dt = oldest_dt.replace(tzinfo=timezone.utc)
            age_seconds = max(0, int((utcnow() - oldest_dt).total_seconds()))
        except ValueError:
            pass
    failed = db.execute(select(func.count()).where(OutboxEvent.status == "failed")).scalar_one()
    return {"pending": int(pending_count), "failed": int(failed), "oldest_pending_age_seconds": age_seconds}


def integrations_status(db: Session, tenant_id, rabbitmq_state: dict) -> dict:
    """پایش اتصال‌ها، Outbox، checkpointها و کارهای Snapshot (FR-17)."""
    installations = list_installations(db, tenant_id)
    checkpoints = {str(cp.installation_id): cp for cp in db.execute(
        select(SyncCheckpoint).where(SyncCheckpoint.tenant_id == tenant_id)).scalars()}
    counter = db.execute(select(TenantChangeCounter).where(
        TenantChangeCounter.tenant_id == tenant_id)).scalar_one_or_none()
    current_max = int(counter.last_seq) if counter else 0
    inst_items = []
    for inst in installations:
        cp = checkpoints.get(str(inst.id))
        lag = None
        if cp is not None:
            lag = max(0, current_max - int(cp.cursor_seq))
        inst_items.append({
            "installation_code": inst.installation_code, "title": inst.title, "mode": inst.mode,
            "status": inst.status, "last_seen_at": inst.last_seen_at,
            "checkpoint_cursor": int(cp.cursor_seq) if cp else None,
            "checkpoint_acknowledged_at": cp.acknowledged_at if cp else None,
            "lag": lag,
        })
    return {
        "tenant": {"id": str(tenant_id)},
        "max_seq": current_max,
        "rabbitmq": rabbitmq_state,
        "outbox": outbox_stats(db),
        "installations": inst_items,
        "recent_snapshots": [{
            "id": str(j.id), "status": j.status, "boundary_seq": j.boundary_seq,
            "created_at": j.created_at.isoformat(),
        } for j in db.execute(select(SnapshotJob).where(SnapshotJob.tenant_id == tenant_id)
                              .order_by(SnapshotJob.created_at.desc()).limit(5)).scalars()],
    }


def tenant_stats(db: Session, tenant_id) -> dict:
    persons_by_status = dict(db.execute(
        select(Person.status, func.count()).where(Person.tenant_id == tenant_id)
        .group_by(Person.status)).all())
    return {
        "persons_total": sum(persons_by_status.values()),
        "persons_active": persons_by_status.get(statuses.PERSON_ACTIVE, 0),
        "persons_inactive": persons_by_status.get(statuses.PERSON_INACTIVE, 0),
        "persons_merged": persons_by_status.get(statuses.PERSON_MERGED, 0),
        "open_change_requests": int(db.execute(select(func.count()).where(
            ChangeRequest.tenant_id == tenant_id, ChangeRequest.status == "open")).scalar_one()),
        "open_quality_cases": int(db.execute(select(func.count()).where(
            ResolutionCase.tenant_id == tenant_id, ResolutionCase.status == "open")).scalar_one()),
    }
