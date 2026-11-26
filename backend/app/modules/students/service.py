"""منطق کسب‌وکار دانشجویان — ثبت دستی، ویرایش نسخه‌دار و همگام‌سازی دانشگاه هوشمند (فضایار۳۶۰).

قرارداد همگام‌سازی (هر دو جهت):
- pull:  GET {SMART_UNI_BASE_URL}{SMART_UNI_STUDENTS_PATH}  → {"items":[...], "total": n}
- push:  POST /api/v1/students/ingest با هدر X-Api-Key  ← مبدأ دانشجوها را می‌فرستد.
mapping و قرارداد کامل: docs/08-students-integration.md
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.common import statuses
from app.common.events import EventType, build_event, record_audit, record_change
from app.core.errors import AppError, conflict, not_found, version_conflict
from app.core.security import Actor
from app.modules.students.models import (
    DEGREE_ALIASES, SOURCE_STATUS_ALIASES, STUDENT_STATUSES, Student,
)
from app.modules.students import repository as repo

STUDENT_FIELDS = (
    "first_name", "last_name", "father_name", "gender", "birth_date",
    "mobile", "phone", "email", "city", "province", "address",
    "university_code", "university_name", "major_code", "major_name",
    "degree_level", "entrance_year", "notes",
)

SYNC_FIELDS = set(STUDENT_FIELDS) | {"status"}


def normalize_degree(value: str | None) -> str:
    """کد کانونی مقطع — پذیرش کد یا برچسب فارسی رایج."""
    if not value:
        return ""
    key = value.strip()
    if key in DEGREE_ALIASES:
        return DEGREE_ALIASES[key]
    low = key.lower().replace("-", "_").replace(" ", "_")
    return DEGREE_ALIASES.get(low, key)


def normalize_status(value: str | None) -> str:
    if not value:
        return "active"
    key = value.strip()
    if key in SOURCE_STATUS_ALIASES:
        return SOURCE_STATUS_ALIASES[key]
    return key.lower()


def normalize_mobile(value: str | None) -> str:
    """یک‌سازی شماره همراه به 09xxxxxxxxx — بدون پرت رکورد در سینک."""
    if not value:
        return ""
    import re
    m = re.sub(r"[\s\-()]", "", value.strip())
    if m.startswith("+98"):
        m = "0" + m[3:]
    elif m.startswith("0098"):
        m = "0" + m[4:]
    if m.startswith("9") and len(m) == 10:
        m = "0" + m
    return m if m.startswith("0") else m


def _student_out(s: Student) -> dict:
    return {
        "id": str(s.id), "student_number": s.student_number, "national_id": s.national_id,
        "first_name": s.first_name, "last_name": s.last_name, "mobile": s.mobile, "city": s.city,
        "university_name": s.university_name, "major_name": s.major_name,
        "degree_level": s.degree_level, "status": s.status, "source": s.source,
        "version": s.version, "updated_at": s.updated_at.isoformat(),
    }


def _student_detail_out(s: Student) -> dict:
    return {
        **_student_out(s),
        "father_name": s.father_name, "gender": s.gender, "birth_date": s.birth_date,
        "phone": s.phone, "email": s.email, "province": s.province, "address": s.address,
        "university_code": s.university_code, "major_code": s.major_code,
        "entrance_year": s.entrance_year, "notes": s.notes,
        "ext_ref": s.ext_ref, "synced_at": s.synced_at, "sync_batch": s.sync_batch,
        "created_at": s.created_at.isoformat(),
    }


# ---------------------------------------------------------------- ثبت دستی

def create_student(db: Session, tenant_id, actor: Actor, data: dict, request=None,
                   correlation_id: str | None = None) -> dict:
    if repo.get_by_student_number(db, tenant_id, data["student_number"]) is not None:
        raise conflict(
            "STUDENT_NUMBER_DUPLICATE",
            "این شماره دانشجویی قبلاً برای دانشجوی دیگری ثبت شده است.",
        )
    student = Student(
        tenant_id=tenant_id,
        student_number=data["student_number"].strip(),
        national_id=(data.get("national_id") or "").strip(),
        first_name=data["first_name"].strip(), last_name=data["last_name"].strip(),
        father_name=(data.get("father_name") or "").strip(),
        gender=data.get("gender") or "", birth_date=(data.get("birth_date") or "").strip(),
        mobile=data["mobile"].strip(), phone=(data.get("phone") or "").strip(),
        email=(data.get("email") or "").strip(),
        city=data["city"].strip(), province=(data.get("province") or "").strip(),
        address=(data.get("address") or "").strip(),
        university_code=(data.get("university_code") or "").strip(),
        university_name=data["university_name"].strip(),
        major_code=(data.get("major_code") or "").strip(),
        major_name=data["major_name"].strip(),
        degree_level=normalize_degree(data["degree_level"]),
        entrance_year=data.get("entrance_year"),
        notes=(data.get("notes") or "").strip(),
        status=statuses.PERSON_ACTIVE, source="manual", version=1,
        created_by=actor.audit_id(), updated_by=actor.audit_id(),
    )
    db.add(student)
    db.flush()
    event = build_event(EventType.STUDENT_CREATED, tenant_id, "student", student.id, student.version,
                        {"student_number": student.student_number,
                         "first_name": student.first_name, "last_name": student.last_name},
                        correlation_id)
    record_change(db, tenant_id, "student", student.id, student.version, "create",
                  ["student_number", "first_name", "last_name"],
                  {k: student.__dict__[k] for k in ("student_number", "first_name", "last_name")},
                  actor, events=[event])
    record_audit(db, tenant_id, actor, "student.create", "student", str(student.id), None,
                 _student_out(student), request=request, correlation_id=correlation_id)
    return _student_out(student)


def update_student(db: Session, tenant_id, actor: Actor, student_id, changes: dict,
                   expected_version: int, request=None, correlation_id: str | None = None) -> dict:
    student = repo.get_student(db, tenant_id, student_id)
    if student is None:
        raise not_found()

    before = _student_out(student)
    values = {}
    for k in STUDENT_FIELDS:
        if k in changes and changes[k] is not None:
            v = changes[k]
            values[k] = v.strip() if isinstance(v, str) else v
    if not values:
        return _student_out(student)  # بدون تغییر نسخه
    if "degree_level" in values:
        values["degree_level"] = normalize_degree(values["degree_level"])
    if "mobile" in values:
        values["mobile"] = normalize_mobile(values["mobile"])

    from sqlalchemy import update
    values["version"] = student.version + 1
    values["updated_by"] = actor.audit_id()
    res = db.execute(
        update(Student)
        .where(Student.id == student.id, Student.tenant_id == tenant_id,
               Student.version == expected_version)
        .values(**values)
    )
    if res.rowcount == 0:
        raise version_conflict(current_version=student.version)
    db.flush()
    db.refresh(student)

    changed_fields = [k for k in values if k not in ("version", "updated_by")]
    payload = {k: getattr(student, k) for k in changed_fields}
    event = build_event(EventType.STUDENT_UPDATED, tenant_id, "student", student.id, student.version,
                        {"changedFields": changed_fields, **payload}, correlation_id)
    record_change(db, tenant_id, "student", student.id, student.version, "update", changed_fields,
                  {"changedFields": changed_fields, **payload}, actor, events=[event])
    record_audit(db, tenant_id, actor, "student.update", "student", str(student.id), before,
                 _student_out(student), request=request, correlation_id=correlation_id)
    return _student_out(student)


def deactivate_student(db: Session, tenant_id, actor: Actor, student_id, expected_version: int,
                       reason: str | None = None, request=None,
                       correlation_id: str | None = None) -> dict:
    student = repo.get_student(db, tenant_id, student_id)
    if student is None:
        raise not_found()
    if student.status == statuses.PERSON_INACTIVE:
        raise conflict("STUDENT_NOT_ACTIVE", "دانشجو قبلاً غیرفعال شده است.")

    from sqlalchemy import update
    from app.common.db import utcnow
    res = db.execute(
        update(Student)
        .where(Student.id == student.id, Student.tenant_id == tenant_id,
               Student.version == expected_version)
        .values(status=statuses.PERSON_INACTIVE, version=student.version + 1,
                updated_by=actor.audit_id())
    )
    if res.rowcount == 0:
        raise version_conflict(current_version=student.version)
    db.flush()
    db.refresh(student)

    event = build_event(EventType.STUDENT_DEACTIVATED, tenant_id, "student", student.id,
                        student.version, {"reason": reason}, correlation_id)
    record_change(db, tenant_id, "student", student.id, student.version, "deactivate", ["status"],
                  {"status": student.status, "reason": reason}, actor, events=[event])
    record_audit(db, tenant_id, actor, "student.deactivate", "student", str(student.id),
                 {"status": "active"}, {"status": "inactive", "reason": reason},
                 request=request, correlation_id=correlation_id)
    return _student_out(student)


def student_detail(db: Session, tenant_id, student_id) -> dict:
    s = repo.get_student(db, tenant_id, student_id)
    if s is None:
        raise not_found()
    return _student_detail_out(s)


def list_students(db: Session, tenant_id, *, q: str | None, degree_level: str | None,
                  university_code: str | None, city: str | None, status: str | None,
                  source: str | None, limit: int, offset: int) -> dict:
    items, total = repo.list_students(db, tenant_id, q=q, degree_level=degree_level,
                                      university_code=university_code, city=city, status=status,
                                      source=source, limit=limit, offset=offset)
    return {"items": [_student_out(s) for s in items], "total": total,
            "limit": limit, "offset": offset}


def stats(db: Session, tenant_id) -> dict:
    return {
        "total": sum(repo.status_distribution(db, tenant_id).values()),
        "by_status": repo.status_distribution(db, tenant_id),
        "by_degree": repo.degree_distribution(db, tenant_id),
        "by_source": repo.source_distribution(db, tenant_id),
        "last_synced_at": repo.last_synced_at(db, tenant_id),
    }


# ------------------------------------------------ همگام‌سازی دانشگاه هوشمند (فضایار۳۶۰)

def _upsert_from_remote(db: Session, tenant_id, actor: Actor, item: dict, batch_id: str,
                        synced_at: str, mode: str) -> tuple[str, dict | None]:
    """یک رکورد مبدأ را بر اساس ext_ref → national_id → student_number upsert می‌کند."""
    ext_ref = str(item.get("external_ref") or item.get("ext_ref") or "").strip()
    student_number = str(item.get("student_number") or "").strip()
    national_id = "".join(ch for ch in str(item.get("national_id") or "") if ch.isdigit())

    if not student_number and not national_id:
        return "skipped", {"ref": ext_ref or (item.get("first_name", "") + " " + item.get("last_name", "")).strip(),
                           "reason": "بدون شماره دانشجویی و کد ملی — رکورد قابل نگاشت نیست"}

    target = None
    if ext_ref:
        target = repo.get_by_ext_ref(db, tenant_id, ext_ref)
    if target is None and national_id:
        target = repo.get_by_national_id(db, tenant_id, national_id)
    if target is None and student_number:
        target = repo.get_by_student_number(db, tenant_id, student_number)

    values = {
        "first_name": str(item.get("first_name") or "").strip(),
        "last_name": str(item.get("last_name") or "").strip(),
        "father_name": str(item.get("father_name") or "").strip(),
        "gender": str(item.get("gender") or "").strip().lower(),
        "birth_date": str(item.get("birth_date") or "").strip(),
        "mobile": normalize_mobile(item.get("mobile")),
        "phone": str(item.get("phone") or "").strip(),
        "email": str(item.get("email") or "").strip(),
        "city": str(item.get("city") or "").strip(),
        "province": str(item.get("province") or "").strip(),
        "university_code": str(item.get("university_code") or item.get("campus_code") or "").strip(),
        "university_name": str(item.get("university_name") or item.get("university") or "").strip(),
        "major_code": str(item.get("major_code") or item.get("field_code") or "").strip(),
        "major_name": str(item.get("major_name") or item.get("major") or item.get("field_of_study") or "").strip(),
        "degree_level": normalize_degree(item.get("degree_level") or item.get("degree")),
        "entrance_year": item.get("entrance_year") or None,
        "status": normalize_status(item.get("status")),
        "source": "smart_university", "ext_ref": ext_ref or None,
    }
    # meta سینک در مقایسه «بدون تغییر» لحاظ نمی‌شود — هر سینک batch تازه دارد
    sync_meta = {"synced_at": synced_at, "sync_batch": batch_id}
    # شماره دانشجویی حل‌شده: مبدأ → ext_ref → کد ملی (اگر مبدأ نفرستد رکورد بی‌شماره نمی‌ماند)
    resolved_number = student_number or ext_ref or national_id
    values["student_number"] = resolved_number

    if not values["first_name"] or not values["last_name"] or not values["university_name"] \
            or not values["major_name"] or not values["degree_level"]:
        who = ext_ref or student_number or national_id
        return "skipped", {"ref": who, "reason": "فیلدهای الزامی مبدأ ناقص است (نام/دانشگاه/رشته/مقطع)"}

    if target is None:
        if resolved_number and repo.get_by_student_number(db, tenant_id, resolved_number) is not None:
            return "skipped", {"ref": resolved_number,
                               "reason": "شماره دانشجویی با رکورد دستی دیگری تداخل دارد"}
        student = Student(tenant_id=tenant_id, national_id=national_id, version=1,
                          created_by=actor.audit_id(), updated_by=actor.audit_id(), **values)
        db.add(student)
        db.flush()
        return "created", None

    changed = {k: v for k, v in values.items() if v != getattr(target, k)}
    if not changed:
        for k, v in sync_meta.items():
            setattr(target, k, v)
        db.flush()
        return "unchanged", None
    for k, v in {**values, **sync_meta}.items():
        setattr(target, k, v)
    target.version = target.version + 1
    target.updated_by = actor.audit_id()
    db.flush()
    return "updated", None


def sync_from_smart_university(db: Session, tenant_id, actor: Actor, request=None,
                               correlation_id: str | None = None, fetch=None) -> dict:
    """Pull از سامانه دانشگاه هوشمند — قرارداد: GET {base}{path} با صفحه‌بندی items/total."""
    from app.core.config import settings
    from app.common.db import utcnow

    batch_id = str(uuid.uuid4())
    synced_at = utcnow().isoformat()
    base = settings.SMART_UNI_BASE_URL.rstrip("/")
    path = settings.SMART_UNI_STUDENTS_PATH or "/api/v1/students"
    limit = 200

    def _default_fetch(url: str, headers: dict) -> tuple[int, dict]:
        import httpx
        with httpx.Client(timeout=settings.EXTERNAL_HTTP_TIMEOUT) as cli:
            resp = cli.get(url, headers=headers)
            try:
                return resp.status_code, resp.json()
            except Exception:  # noqa: BLE001
                return resp.status_code, {}

    fetch = fetch or _default_fetch

    items: list[dict] = []
    remote_status: int | None = None
    message = ""
    try:
        offset = 0
        headers = {}
        if settings.SMART_UNI_API_KEY:
            headers["X-API-Key"] = settings.SMART_UNI_API_KEY
        while True:
            url = f"{base}{path}?limit={limit}&offset={offset}"
            code, body = fetch(url, headers)
            remote_status = code
            if code != 200:
                message = ("سامانه دانشگاه هوشمند پاسخ موفق نداد؛ قرارداد انتگراسیون در "
                           "docs/08-students-integration.md مستند است.")
                break
            chunk = body.get("items", body if isinstance(body, list) else [])
            items.extend(chunk)
            total = body.get("total", len(items))
            offset += limit
            if len(items) >= total or not chunk:
                break
    except Exception as exc:  # noqa: BLE001
        remote_status = None
        message = (f"ارتباط با دانشگاه هوشمند برقرار نشد ({type(exc).__name__}). "
                   "قرارداد در docs/08-students-integration.md مستند است.")

    created = updated = unchanged = 0
    skipped: list[dict] = []
    for item in items:
        try:
            outcome, note = _upsert_from_remote(db, tenant_id, actor, item, batch_id, synced_at,
                                                mode="pull")
            if outcome == "created":
                created += 1
            elif outcome == "updated":
                updated += 1
            elif outcome == "unchanged":
                unchanged += 1
            elif note:
                skipped.append(note)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"ref": str(item.get("external_ref") or item.get("student_number") or "?"),
                            "reason": f"خطا در پردازش رکورد: {type(exc).__name__}"})

    if created or updated:
        record_audit(db, tenant_id, actor, "student.sync.pull", "student_batch", batch_id, None,
                     {"total_remote": len(items), "created": created, "updated": updated,
                      "unchanged": unchanged, "skipped": len(skipped), "remote_status": remote_status},
                     request=request, correlation_id=correlation_id)

    if message and not items:
        final_message = message
    elif remote_status == 200 and not items:
        final_message = "اتصال موفق بود اما سامانه مبدأ فهرستی برنگرداند — قرارداد را با تیم فضایار چک کنید."
    else:
        final_message = message

    return {
        "batch_id": batch_id, "mode": "pull", "remote_status": remote_status,
        "total_remote": len(items), "created": created, "updated": updated,
        "unchanged": unchanged, "skipped": skipped, "message": final_message,
        "synced_at": synced_at,
    }


def ingest_from_smart_university(db: Session, tenant_id, actor: Actor, items: list[dict],
                                 request=None, correlation_id: str | None = None) -> dict:
    """Push از سمت دانشگاه هوشمند — همان نگاشت pull؛ اعتبار با کلید API انجام شده است."""
    from app.common.db import utcnow
    batch_id = str(uuid.uuid4())
    synced_at = utcnow().isoformat()
    created = updated = unchanged = 0
    skipped: list[dict] = []
    for item in items:
        outcome, note = _upsert_from_remote(db, tenant_id, actor, item, batch_id, synced_at, mode="push")
        if outcome == "created":
            created += 1
        elif outcome == "updated":
            updated += 1
        elif outcome == "unchanged":
            unchanged += 1
        elif note:
            skipped.append(note)
    if created or updated:
        record_audit(db, tenant_id, actor, "student.sync.push", "student_batch", batch_id, None,
                     {"total_remote": len(items), "created": created, "updated": updated,
                      "unchanged": unchanged, "skipped": len(skipped)},
                     request=request, correlation_id=correlation_id)
    return {
        "batch_id": batch_id, "mode": "push", "remote_status": None,
        "total_remote": len(items), "created": created, "updated": updated,
        "unchanged": unchanged, "skipped": skipped,
        "message": "دریافت موفق از دانشگاه هوشمند" if items else "بدون رکورد در پیام",
        "synced_at": synced_at,
    }
