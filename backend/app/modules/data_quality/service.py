"""منطق کیفیت داده: کشف نامزد تکرار، پرونده، تصمیم انسانی و ادغام کنترل‌شده (FR-13، بخش ۱۲).

شباهت نام فقط نامزد ایجاد می‌کند؛ تصمیم نهایی همیشه انسانی است.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import statuses
from app.common.db import utcnow
from app.common.events import EventType, build_event, record_audit, record_change
from app.core.errors import conflict, not_found
from app.core.security import Actor
from app.modules.data_quality.models import MergeRecord, ResolutionCase
from app.modules.identities.models import ExternalIdMapping
from app.modules.persons.models import Person, PersonIdentifier


def _norm(name: str) -> str:
    return " ".join((name or "").split()).lower()


def scan_duplicates(db: Session, tenant_id) -> list[dict]:
    """نامزدها: نام یکسان (شواهد ضعیف) یا شناسه تأییدشده یکسان (شواهد قوی)."""
    suggestions: dict[str, dict] = {}
    rows = list(db.execute(
        select(Person.id, Person.given_name, Person.family_name, Person.display_name)
        .where(Person.tenant_id == tenant_id, Person.status == statuses.PERSON_ACTIVE)
    ).all())
    by_name: dict[str, list] = {}
    for pid, given, family, display in rows:
        by_name.setdefault(_norm(f"{given} {family}"), []).append(
            {"person_id": str(pid), "display_name": display})
    for key, members in by_name.items():
        if len(members) > 1:
            for m in members:
                suggestions.setdefault(m["person_id"], {
                    "matched_by": [], "group": []})
            for m in members:
                suggestions[m["person_id"]]["matched_by"].append("same_name")
    # شناسه تأییدشده یکسان
    ident_rows = list(db.execute(
        select(PersonIdentifier.person_id, PersonIdentifier.value_hash, PersonIdentifier.type)
        .where(PersonIdentifier.tenant_id == tenant_id,
               PersonIdentifier.status == "active",
               PersonIdentifier.verification_status == "verified")
    ).all())
    by_hash: dict[tuple, list] = {}
    for pid, vh, itype in ident_rows:
        by_hash.setdefault((vh, itype), []).append(pid)
    for (vh, itype), pids in by_hash.items():
        if len(set(pids)) > 1:
            for pid in set(pids):
                entry = suggestions.setdefault(str(pid), {"matched_by": [], "group": []})
                if "same_verified_identifier" not in entry["matched_by"]:
                    entry["matched_by"].append("same_verified_identifier")
    # گروه‌بندی خروجی
    groups: dict[tuple, list] = {}
    for pid, entry in suggestions.items():
        key = tuple(sorted(set(entry["matched_by"])))
        groups.setdefault(key, [])
        groups[key].append(pid)
    out = []
    for matched_by, pids in groups.items():
        members = []
        for pid in pids:
            p = db.execute(select(Person).where(Person.id == uuid.UUID(pid))).scalar_one_or_none()
            if p is not None and p.status == statuses.PERSON_ACTIVE:
                members.append({"person_id": str(p.id), "display_name": p.display_name,
                                "version": p.version, "created_at": p.created_at.isoformat()})
        if len(members) > 1:
            out.append({"matched_by": list(matched_by), "candidates": members,
                        "evidence": {"method": "duplicate_scan",
                                     "note": "شباهت نام/شناسه فقط نامزد ایجاد می‌کند؛ تصمیم نیازمند بررسی انسانی است."}})
    return out


def create_case(db: Session, tenant_id, actor: Actor, data: dict, request=None) -> dict:
    candidate_ids = data["candidate_ids"]
    if len(candidate_ids) < 2:
        raise conflict("CANDIDATES_REQUIRED", "حداقل دو نامزد برای پرونده تکرار لازم است.")
    persons = []
    for pid in candidate_ids:
        p = db.execute(select(Person).where(
            Person.tenant_id == tenant_id, Person.id == uuid.UUID(str(pid)))).scalar_one_or_none()
        if p is None:
            raise not_found(f"نامزد {pid} یافت نشد.")
        persons.append(p)
    evidence = data.get("evidence") or {}
    evidence.setdefault("persons", [{
        "person_id": str(p.id), "display_name": p.display_name, "status": p.status,
        "version": p.version,
        "identifiers": [{"type": i.type, "issuer": i.issuer, "value_masked": i.value_masked,
                         "verification_status": i.verification_status}
                        for i in db.execute(select(PersonIdentifier).where(
                            PersonIdentifier.tenant_id == tenant_id,
                            PersonIdentifier.person_id == p.id,
                            PersonIdentifier.status == "active")).scalars().all()],
    } for p in persons])
    case = ResolutionCase(tenant_id=tenant_id, candidate_ids=[str(p) for p in candidate_ids],
                          evidence=evidence, status="open", created_by=actor.audit_id())
    db.add(case)
    db.flush()
    record_audit(db, tenant_id, actor, "quality.create_case", "resolution_case", str(case.id), None,
                 {"candidates": case.candidate_ids}, request=request)
    return _case_out(case)


def _case_out(c: ResolutionCase) -> dict:
    return {"id": str(c.id), "candidate_ids": c.candidate_ids, "evidence": c.evidence,
            "status": c.status, "created_by": c.created_by, "decided_by": c.decided_by,
            "decided_at": c.decided_at, "decision": c.decision,
            "merge_record_id": str(c.merge_record_id) if c.merge_record_id else None,
            "created_at": c.created_at.isoformat()}


def list_cases(db: Session, tenant_id, status: str | None, limit: int) -> list[dict]:
    stmt = select(ResolutionCase).where(ResolutionCase.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(ResolutionCase.status == status)
    rows = list(db.execute(stmt.order_by(ResolutionCase.created_at.desc()).limit(limit)).scalars().all())
    return [_case_out(r) for r in rows]


def decide_merge(db: Session, tenant_id, actor: Actor, case_id, target_person_id, note: str | None,
                 request=None, correlation_id: str | None = None) -> dict:
    """ادغام کنترل‌شده: انتخاب شناسه نهایی، انتقال نگاشت‌ها، ثبت سابقه و alias، انتشار PersonMerged."""
    case = db.execute(select(ResolutionCase).where(
        ResolutionCase.tenant_id == tenant_id, ResolutionCase.id == case_id)).scalar_one_or_none()
    if case is None:
        raise not_found("پرونده کیفیت یافت نشد.")
    if case.status != "open":
        raise conflict("CASE_NOT_OPEN", "این پرونده قبلاً تصمیم‌گیری شده است.")
    target_id = str(target_person_id)
    if target_id not in [str(c) for c in case.candidate_ids]:
        raise conflict("TARGET_NOT_CANDIDATE", "شناسه نهایی باید یکی از نامزدهای پرونده باشد.")
    target = db.execute(select(Person).where(
        Person.tenant_id == tenant_id, Person.id == uuid.UUID(target_id))).scalar_one_or_none()
    if target is None or target.status != statuses.PERSON_ACTIVE:
        raise conflict("TARGET_NOT_ACTIVE", "شخص هدف باید فعال باشد.")
    sources = []
    for cid in case.candidate_ids:
        if str(cid) == target_id:
            continue
        p = db.execute(select(Person).where(
            Person.tenant_id == tenant_id, Person.id == uuid.UUID(str(cid)))).scalar_one_or_none()
        if p is None or p.status != statuses.PERSON_ACTIVE:
            raise conflict("SOURCE_NOT_ACTIVE", f"نامزد {cid} فعال نیست و قابل ادغام نیست.")
        sources.append(p)

    merge_record = MergeRecord(
        tenant_id=tenant_id, source_person_id=sources[0].id, target_person_id=target.id,
        decided_by=actor.audit_id(), decision_note=note, case_id=case.id, status="applied",
        alias_snapshot={"sources": [{"id": str(p.id), "display_name": p.display_name,
                                     "version": p.version} for p in sources]},
    )
    db.add(merge_record)
    db.flush()

    transferred, skipped = [], []
    for source in sources:
        source.status = statuses.PERSON_MERGED
        source.merged_into_id = target.id
        source.version += 1
        # انتقال نگاشت‌های شناسه محلی به شناسه نهایی
        mappings = list(db.execute(select(ExternalIdMapping).where(
            ExternalIdMapping.tenant_id == tenant_id,
            ExternalIdMapping.entity_type == "person",
            ExternalIdMapping.entity_id == source.id)).scalars().all())
        for m in mappings:
            dup = db.execute(select(ExternalIdMapping).where(
                ExternalIdMapping.tenant_id == tenant_id,
                ExternalIdMapping.installation_id == m.installation_id,
                ExternalIdMapping.entity_type == "person",
                ExternalIdMapping.local_id == m.local_id,
                ExternalIdMapping.entity_id == target.id)).scalar_one_or_none()
            if dup is not None:
                skipped.append({"mapping_id": str(m.id), "reason": "conflict_with_target"})
                continue
            m.entity_id = target.id
            transferred.append(str(m.id))
        event = build_event(EventType.PERSON_MERGED, tenant_id, "person", source.id, source.version,
                            {"sourceId": str(source.id), "targetId": str(target.id),
                             "transferredMappings": transferred, "skippedMappings": skipped},
                            correlation_id)
        record_change(db, tenant_id, "person", source.id, source.version, "merge",
                      ["status", "merged_into_id"],
                      {"sourceId": str(source.id), "targetId": str(target.id)}, actor, events=[event])
    case.status = "decided"
    case.decided_by = actor.audit_id()
    case.decided_at = utcnow().isoformat()
    case.decision = {"merge_into": target_id, "note": note,
                     "transferred_mappings": transferred, "skipped_mappings": skipped}
    case.merge_record_id = merge_record.id
    db.flush()
    record_audit(db, tenant_id, actor, "quality.merge_persons", "person", str(target.id),
                 {"sources": [str(p.id) for p in sources]},
                 {"merged_into": target_id, "transferred": transferred, "skipped": skipped},
                 request=request, note=note)
    return {"case": _case_out(case), "merge_record_id": str(merge_record.id),
            "target_person_id": target_id, "transferred_mappings": transferred,
            "skipped_mappings": skipped}


def reverse_merge(db: Session, tenant_id, actor: Actor, merge_id, note: str | None, request=None) -> dict:
    """بازگردانی ادغام — فرآیند اصلاحی مستقل (بخش ۱۲.۲)."""
    record = db.execute(select(MergeRecord).where(
        MergeRecord.tenant_id == tenant_id, MergeRecord.id == merge_id)).scalar_one_or_none()
    if record is None:
        raise not_found("سابقه ادغام یافت نشد.")
    if record.status != "applied":
        raise conflict("MERGE_ALREADY_REVERSED", "این ادغام قبلاً بازگردانی شده است.")
    source = db.execute(select(Person).where(
        Person.tenant_id == tenant_id, Person.id == record.source_person_id)).scalar_one_or_none()
    if source is None:
        raise not_found("شخص ادغام‌شده یافت نشد.")
    source.status = statuses.PERSON_ACTIVE
    source.merged_into_id = None
    source.version += 1
    record.status = "reversed"
    record.reversed_by = actor.audit_id()
    record.reversed_at = utcnow().isoformat()
    event = build_event(EventType.PERSON_MERGE_CORRECTED, tenant_id, "person", source.id, source.version,
                        {"restoredId": str(source.id), "mergeRecordId": str(record.id), "note": note},
                        None)
    record_change(db, tenant_id, "person", source.id, source.version, "merge_corrected",
                  ["status"], {"restoredId": str(source.id)}, actor, events=[event])
    record_audit(db, tenant_id, actor, "quality.reverse_merge", "person", str(source.id),
                 {"status": "merged"}, {"status": "active", "merge_record": str(record.id)},
                 request=request, note=note)
    db.flush()
    return {"merge_record_id": str(record.id), "restored_person_id": str(source.id),
            "status": record.status}


def list_merge_records(db: Session, tenant_id, limit: int = 50) -> list[dict]:
    rows = list(db.execute(select(MergeRecord).where(
        MergeRecord.tenant_id == tenant_id).order_by(MergeRecord.created_at.desc()).limit(limit)).scalars().all())
    return [{
        "id": str(r.id), "source_person_id": str(r.source_person_id),
        "target_person_id": str(r.target_person_id), "decided_by": r.decided_by,
        "decision_note": r.decision_note, "status": r.status, "case_id": str(r.case_id) if r.case_id else None,
        "alias_snapshot": r.alias_snapshot,
        "reversed_by": r.reversed_by, "reversed_at": r.reversed_at,
        "created_at": r.created_at.isoformat(),
    } for r in rows]
