"""منطق همگام‌سازی: Snapshot بدون شکاف، بازیابی تغییرات، Checkpoint و تطبیق (FR-10..FR-12، بخش ۹)."""
from __future__ import annotations

import json
import os
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import statuses
from app.common.db import utcnow
from app.common.events import record_audit
from app.core.config import settings
from app.core.errors import conflict, cursor_expired, not_found
from app.core.security import Actor
from app.modules.identities.models import ExternalIdMapping, IdentityAccountLink
from app.modules.integrations.models import SystemInstallation
from app.modules.organizations.models import Organization
from app.modules.persons.models import Person, PersonIdentifier
from app.modules.synchronization.models import (
    ChangeLog, ReconciliationJob, SnapshotJob, SyncCheckpoint, TenantChangeCounter,
)


def boundary_seq_locked(db: Session, tenant_id) -> int:
    """خواندن مرز تغییر با قفل ردیف شمارنده — هماهنگی Snapshot با تراکنش‌های در جریان (بند ۹.۵)."""
    row = db.execute(
        select(TenantChangeCounter).where(TenantChangeCounter.tenant_id == tenant_id).with_for_update()
    ).scalar_one_or_none()
    return int(row.last_seq) if row else 0


def create_snapshot_job(db: Session, tenant_id, actor: Actor, data: dict, request=None) -> SnapshotJob:
    job = SnapshotJob(
        tenant_id=tenant_id, requested_by_installation_id=data.get("installation_id"),
        requested_by=actor.audit_id(), scope={"entities": data.get("entities") or ["persons", "organizations"]},
        status=statuses.JOB_QUEUED,
        expires_at=(utcnow() + timedelta(hours=settings.SNAPSHOT_TTL_HOURS)).isoformat(),
    )
    db.add(job)
    db.flush()
    record_audit(db, tenant_id, actor, "sync.snapshot.create", "snapshot_job", str(job.id), None,
                 {"scope": job.scope}, request=request)
    return job


def _job_out(job: SnapshotJob) -> dict:
    return {
        "id": str(job.id), "tenant_id": str(job.tenant_id), "scope": job.scope, "status": job.status,
        "boundary_seq": job.boundary_seq, "counts": job.counts, "error": job.error,
        "expires_at": job.expires_at,
        "download_url": f"{settings.API_PREFIX}/sync/snapshots/{job.id}/download" if job.status == statuses.JOB_DONE else None,
        "created_at": job.created_at.isoformat(),
    }


def run_snapshot_job(db: Session, job_id) -> SnapshotJob:
    """تولید Snapshot از نمای سازگار: قفل شمارنده → مرز → خواندن داده در همان تراکنش.

    با قفل ردیف شمارنده، هیچ تراکنش تغییری نمی‌تواند در فاصله تعیین مرز و خواندن داده
    Commit کند؛ بنابراین هیچ تغییر Commit‌شده‌ای از قلم نمی‌افتد.
    """
    job = db.execute(select(SnapshotJob).where(SnapshotJob.id == job_id)).scalar_one_or_none()
    if job is None or job.status in (statuses.JOB_DONE, statuses.JOB_EXPIRED):
        return job
    job.status = statuses.JOB_RUNNING
    db.commit()
    try:
        boundary = boundary_seq_locked(db, job.tenant_id)  # قفل تا پایان تراکنش
        entities = (job.scope or {}).get("entities") or ["persons", "organizations"]
        snapshot: dict = {
            "schemaVersion": 1,
            "tenantId": str(job.tenant_id),
            "boundarySeq": boundary,
            "generatedAt": utcnow().isoformat(),
            "entities": {},
        }
        counts: dict = {}
        if "persons" in entities:
            persons = list(db.execute(select(Person).where(Person.tenant_id == job.tenant_id)).scalars().all())
            idents = {str(p.id): [] for p in persons}
            for i in db.execute(select(PersonIdentifier).where(
                    PersonIdentifier.tenant_id == job.tenant_id, PersonIdentifier.status == "active")).scalars():
                idents.setdefault(str(i.person_id), []).append({
                    "type": i.type, "issuer": i.issuer, "value_masked": i.value_masked,
                    "verification_status": i.verification_status})
            snapshot["entities"]["persons"] = [{
                "id": str(p.id), "given_name": p.given_name, "family_name": p.family_name,
                "display_name": p.display_name, "status": p.status, "version": p.version,
                "merged_into_id": str(p.merged_into_id) if p.merged_into_id else None,
                "identifiers": idents.get(str(p.id), []),
            } for p in persons]
            counts["persons"] = len(persons)
        if "organizations" in entities:
            orgs = list(db.execute(select(Organization).where(
                Organization.tenant_id == job.tenant_id)).scalars().all())
            snapshot["entities"]["organizations"] = [{
                "id": str(o.id), "parent_id": str(o.parent_id) if o.parent_id else None,
                "type": o.type, "code": o.code, "name": o.name, "status": o.status, "version": o.version,
            } for o in orgs]
            counts["organizations"] = len(orgs)
        if "account_links" in entities:
            links = list(db.execute(select(IdentityAccountLink).where(
                IdentityAccountLink.tenant_id == job.tenant_id,
                IdentityAccountLink.status == "active")).scalars().all())
            snapshot["entities"]["account_links"] = [{
                "person_id": str(l.person_id), "issuer": l.issuer, "subject": l.subject,
                "status": l.status,
            } for l in links]
            counts["account_links"] = len(links)
        if "mappings" in entities:
            mappings = list(db.execute(select(ExternalIdMapping).where(
                ExternalIdMapping.tenant_id == job.tenant_id)).scalars().all())
            snapshot["entities"]["mappings"] = [{
                "installation_id": str(m.installation_id), "entity_type": m.entity_type,
                "local_id": m.local_id, "entity_id": str(m.entity_id), "status": m.status,
            } for m in mappings]
            counts["mappings"] = len(mappings)

        os.makedirs(os.path.join(settings.DATA_DIR, "snapshots"), exist_ok=True)
        path = os.path.join(settings.DATA_DIR, "snapshots", f"{job.id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, ensure_ascii=False)
        job.file_path = path
        job.boundary_seq = boundary
        job.counts = counts
        job.status = statuses.JOB_DONE
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.execute(select(SnapshotJob).where(SnapshotJob.id == job_id)).scalar_one()
        job.status = statuses.JOB_FAILED
        job.error = f"{type(exc).__name__}: {exc}"
        db.commit()
    return job


def get_snapshot_job(db: Session, tenant_id, job_id) -> SnapshotJob:
    job = db.execute(select(SnapshotJob).where(
        SnapshotJob.tenant_id == tenant_id, SnapshotJob.id == job_id)).scalar_one_or_none()
    if job is None:
        raise not_found("کار Snapshot یافت نشد.")
    return job


def snapshot_file(job: SnapshotJob) -> str:
    if job.status != statuses.JOB_DONE or not job.file_path or not os.path.exists(job.file_path):
        raise not_found("خروجی Snapshot در دسترس نیست.")
    return job.file_path


def max_seq(db: Session, tenant_id) -> int:
    row = db.execute(select(TenantChangeCounter).where(
        TenantChangeCounter.tenant_id == tenant_id)).scalar_one_or_none()
    return int(row.last_seq) if row else 0


def list_changes(db: Session, tenant_id, cursor: int | None, limit: int) -> dict:
    """بازیابی تغییرات جبرانی پس از cursor؛ cursor منقضی → 410 و الزام Snapshot مجدد."""
    current_max = max_seq(db, tenant_id)
    if cursor is not None and cursor >= 0:
        oldest_retained = max(0, current_max - settings.CHANGE_RETENTION_MIN)
        if cursor < oldest_retained:
            raise cursor_expired()
    stmt = select(ChangeLog).where(ChangeLog.tenant_id == tenant_id)
    if cursor is not None and cursor >= 0:
        stmt = stmt.where(ChangeLog.seq > cursor)
    rows = list(db.execute(stmt.order_by(ChangeLog.seq).limit(limit + 1)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "changes": [{
            "seq": r.seq, "occurred_at": r.occurred_at, "entity_type": r.entity_type,
            "entity_id": r.entity_id, "entity_version": r.entity_version,
            "operation": r.operation, "changed_fields": r.changed_fields, "data": r.data,
        } for r in rows],
        "cursor_next": rows[-1].seq if rows else (cursor or 0),
        "has_more": has_more,
        "max_seq": current_max,
    }


def upsert_checkpoint(db: Session, tenant_id, actor: Actor, data: dict, request=None) -> dict:
    inst = db.execute(select(SystemInstallation).where(
        SystemInstallation.tenant_id == tenant_id,
        (SystemInstallation.id == data.get("installation_id")) |
        (SystemInstallation.installation_code == data.get("installation_code")))).scalar_one_or_none()
    if inst is None:
        raise not_found("نصب موردنظر یافت نشد.")
    scope = data.get("scope") or "persons"
    cp = db.execute(select(SyncCheckpoint).where(
        SyncCheckpoint.tenant_id == tenant_id, SyncCheckpoint.installation_id == inst.id,
        SyncCheckpoint.scope == scope)).scalar_one_or_none()
    before = None
    if cp is None:
        cp = SyncCheckpoint(tenant_id=tenant_id, installation_id=inst.id, scope=scope)
        db.add(cp)
    else:
        before = {"cursor_seq": cp.cursor_seq}
    cp.cursor_seq = int(data["cursor"])
    cp.acknowledged_at = utcnow().isoformat()
    cp.note = data.get("note")
    db.flush()
    record_audit(db, tenant_id, actor, "sync.checkpoint", "sync_checkpoint", str(cp.id), before,
                 {"cursor_seq": cp.cursor_seq, "installation": inst.installation_code}, request=request)
    return {"installation_code": inst.installation_code, "scope": scope,
            "cursor_seq": cp.cursor_seq, "acknowledged_at": cp.acknowledged_at}


def create_reconciliation_job(db: Session, tenant_id, actor: Actor, data: dict, request=None) -> dict:
    """تطبیق پایه: مقایسه تعداد و وضعیت با checkpoint مصرف‌کننده (گزارش؛ بدون اصلاح خودکار)."""
    inst = db.execute(select(SystemInstallation).where(
        SystemInstallation.tenant_id == tenant_id,
        (SystemInstallation.id == data.get("installation_id")) |
        (SystemInstallation.installation_code == data.get("installation_code")))).scalar_one_or_none()
    if inst is None:
        raise not_found("نصب موردنظر یافت نشد.")
    scope = data.get("scope") or "persons"
    cp = db.execute(select(SyncCheckpoint).where(
        SyncCheckpoint.tenant_id == tenant_id, SyncCheckpoint.installation_id == inst.id,
        SyncCheckpoint.scope == scope)).scalar_one_or_none()
    current_max = max_seq(db, tenant_id)
    counts = dict(db.execute(
        select(Person.status, func.count()).where(Person.tenant_id == tenant_id)
        .group_by(Person.status)).all())
    report = {
        "installation": inst.installation_code, "scope": scope,
        "core_max_seq": current_max,
        "checkpoint_cursor": cp.cursor_seq if cp else None,
        "checkpoint_acknowledged_at": cp.acknowledged_at if cp else None,
        "lag": (current_max - cp.cursor_seq) if cp else None,
        "core_person_counts_by_status": counts,
        "note": "تطبیق پایه؛ مقایسه کامل سطر‌به‌سطر نیازمند Snapshot و اجرای مصرف‌کننده است.",
    }
    job = ReconciliationJob(tenant_id=tenant_id, installation_id=inst.id, status="done",
                            report=report, created_by=actor.audit_id())
    db.add(job)
    db.flush()
    record_audit(db, tenant_id, actor, "sync.reconciliation", "reconciliation_job", str(job.id),
                 None, report, request=request)
    return {"id": str(job.id), **report}
