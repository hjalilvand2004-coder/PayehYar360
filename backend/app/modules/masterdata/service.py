"""منطق اطلاعات پایه چندسامانه‌ای: همگام‌سازی از منابع خارجی، درج دستی، کاتالوگ سرویس و تاریخچه."""
from __future__ import annotations

import hashlib
import re
import secrets
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.common import statuses
from app.common.events import record_audit
from app.common.jalali import jalali_str
from app.core.config import settings
from app.core.errors import conflict, forbidden, not_found, unauthorized
from app.core.security import Actor
from app.modules.organizations.models import Organization
from app.modules.masterdata.models import (Classroom, CourseSyllabus, CourseSyllabusTopic,
                                           FetchLog, Instructor, ServiceClient)
from app.modules.references.models import ReferenceItem, ReferenceSet

# ---------- دامنه‌های سرویس‌دهی به سایر سامانه‌ها ----------

def _org_items(db: Session, tenant_id) -> list[dict]:
    return [{"code": o.code, "type": o.type, "name": o.name, "parent_code": None,
             "sort_order": o.sort_order, "status": o.status, "updated_at": o.updated_at}
            for o in db.execute(select(Organization).where(
                Organization.tenant_id == tenant_id).order_by(Organization.sort_order)).scalars().all()]


def _instructor_items(db: Session, tenant_id, since: str | None = None) -> list[dict]:
    stmt = select(Instructor).where(Instructor.tenant_id == tenant_id,
                                    Instructor.status == statuses.PERSON_ACTIVE)
    if since:
        stmt = stmt.where(Instructor.updated_at > since)
    return [{"source_code": i.source_code, "full_name": i.full_name, "rank": i.rank,
             "department": i.department, "email": i.email, "phone": i.phone,
             "source": i.source, "updated_at": i.updated_at}
            for i in db.execute(stmt.order_by(Instructor.full_name)).scalars().all()]


def _classroom_items(db: Session, tenant_id, since: str | None = None) -> list[dict]:
    stmt = select(Classroom).where(Classroom.tenant_id == tenant_id,
                                   Classroom.status == statuses.PERSON_ACTIVE)
    if since:
        stmt = stmt.where(Classroom.updated_at > since)
    return [{"source_code": c.source_code, "name": c.name, "kind": c.kind,
             "building": c.building, "capacity": c.capacity, "source": c.source,
             "updated_at": c.updated_at}
            for c in db.execute(stmt.order_by(Classroom.name)).scalars().all()]


def _course_items(db: Session, tenant_id) -> list[dict]:
    sets = {str(s.id): s.code for s in db.execute(select(ReferenceSet).where(
        ReferenceSet.tenant_id == tenant_id)).scalars().all()}
    return [{"set": sets.get(str(i.set_id), ""), "code": i.code, "title": i.title,
             "attrs": i.attrs or {}, "status": i.status, "updated_at": i.updated_at}
            for i in db.execute(select(ReferenceItem).where(
                ReferenceItem.tenant_id == tenant_id,
                ReferenceItem.set_id.in_([uuid.UUID(sid) for sid, code in sets.items() if code == "unique_courses"]))
            ).scalars().all()]


def _ref_items(db: Session, tenant_id, since: str | None = None) -> list[dict]:
    sets = {str(s.id): s.code for s in db.execute(select(ReferenceSet).where(
        ReferenceSet.tenant_id == tenant_id)).scalars().all()}
    stmt = select(ReferenceItem).where(ReferenceItem.tenant_id == tenant_id)
    if since:
        stmt = stmt.where(ReferenceItem.updated_at > since)
    return [{"set": sets.get(str(i.set_id), ""), "code": i.code, "title": i.title,
             "parent_code": None, "status": i.status, "attrs": i.attrs or {},
             "updated_at": i.updated_at}
            for i in db.execute(stmt.order_by(ReferenceItem.set_id, ReferenceItem.sort_order)).scalars().all()]


# ---------- ثبت لاگ ----------

def log_fetch(db: Session, tenant_id, *, direction: str, domain: str, client_code: str | None = None,
              client_id=None, source: str | None = None, endpoint: str | None = None,
              record_count: int = 0, status: str = "success", http_status: int | None = None,
              duration_ms: int | None = None, error: str | None = None,
              correlation_id: str | None = None) -> FetchLog:
    now = datetime.now(timezone.utc)
    log = FetchLog(tenant_id=tenant_id, direction=direction, domain=domain,
                   client_code=client_code, client_id=client_id, source=source,
                   endpoint=endpoint, record_count=record_count, status=status,
                   http_status=http_status, duration_ms=duration_ms, error=error,
                   correlation_id=correlation_id,
                   occurred_at=now.isoformat(timespec="seconds"),
                   occurred_at_jalali=jalali_str(now, with_time=True))
    db.add(log)
    db.flush()
    return log


def _log_out(db: Session, client: ServiceClient, domain: str, endpoint: str,
             record_count: int, duration_ms: int) -> None:
    log_fetch(db, client.tenant_id, direction="out", domain=domain, client_code=client.code,
              client_id=client.id, endpoint=endpoint, record_count=record_count,
              duration_ms=duration_ms, status="success")
    now = datetime.now(timezone.utc)
    client.last_seen_at = now.isoformat(timespec="seconds")
    client.last_seen_at_jalali = jalali_str(now, with_time=True)


# ---------- واکشی سرویس توسط سامانه‌های دیگر ----------

def authenticate_service(db: Session, api_key: str) -> ServiceClient:
    """کلید API → کلاینت؛ کلید فقط hash ذخیره می‌شود و هرگز نمایش داده نمی‌شود."""
    if not api_key:
        raise unauthorized("کلید API ارسال نشده است؛ هدر X-API-Key را تنظیم کنید.")
    h = hashlib.sha256(api_key.encode()).hexdigest()
    client = db.execute(select(ServiceClient).where(
        ServiceClient.api_key_hash == h, ServiceClient.status == "active")).scalar_one_or_none()
    if client is None:
        raise unauthorized("کلید API نامعتبر یا قطع‌شده است.")
    return client


def fetch_domain(db: Session, client: ServiceClient, domain: str, since: str | None,
                 endpoint: str) -> dict:
    if domain not in SERVICE_DOMAINS:
        raise not_found(f"دامنه «{domain}» تعریف نشده است؛ دامنه‌های معتبر: {', '.join(SERVICE_DOMAINS)}")
    if client.scopes and domain not in client.scopes:
        log_fetch(db, client.tenant_id, direction="out", domain=domain, client_code=client.code,
                  client_id=client.id, endpoint=endpoint, status="failed", error="scope_not_allowed")
        db.commit()
        raise forbidden("SCOPE_FORBIDDEN", f"این کلید به دامنه «{domain}» دسترسی ندارد.")
    t0 = time.monotonic()
    title, provider = SERVICE_DOMAINS[domain]
    if domain == "instructors":
        items = _instructor_items(db, client.tenant_id, since)
    elif domain == "classrooms":
        items = _classroom_items(db, client.tenant_id, since)
    elif domain == "organizations":
        items = _org_items(db, client.tenant_id)
    elif domain == "unique-courses":
        items = _course_items(db, client.tenant_id)
    elif domain == "course-syllabi":
        items = _syllabus_items(db, client.tenant_id, since)
    else:
        items = _ref_items(db, client.tenant_id, since)
    duration = int((time.monotonic() - t0) * 1000)
    now = datetime.now(timezone.utc)
    _log_out(db, client, domain, endpoint, len(items), duration)
    db.commit()
    return {
        "ok": True, "domain": domain, "title": title, "count": len(items),
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_jalali": jalali_str(now, with_time=True),
        "items": items,
    }


SERVICE_DOMAINS: dict[str, tuple[str, str]] = {
    "instructors": ("اساتید", "masterdata"),
    "classrooms": ("کلاس‌ها و سالن‌ها", "masterdata"),
    "organizations": ("ساختار سازمانی", "core"),
    "unique-courses": ("درس‌های یکتا", "references"),
    "course-syllabi": ("سرفصل‌های مصوب دروس", "masterdata"),
    "reference-items": ("آیتم‌های مرجع", "references"),
}

# مجموعه‌های سرفصل — برچسب فارسی برای پنل و کاتالوگ
SYLLABI_SETS: dict[str, str] = {
    "1394": "سرفصل‌های مصوب ۱۳۹۴",
    "CE403": "سرفصل مصوب مهندسی کامپیوتر — سری ۴۰۳",
    "NP1400": "سرفصل مصوب ۱۴۰۰ (NP)",
    "MANUAL": "درج دستی",
}


# ---------- کلاینت‌های سرویس ----------

def create_service_client(db: Session, tenant_id, actor: Actor, data: dict) -> dict:
    code = (data.get("code") or "").strip().lower()
    if not code:
        raise conflict("CLIENT_CODE_REQUIRED", "کد سامانه مصرف‌کننده الزامی است.")
    dup = db.execute(select(ServiceClient).where(
        ServiceClient.tenant_id == tenant_id, ServiceClient.code == code)).scalar_one_or_none()
    if dup is not None:
        raise conflict("CLIENT_DUPLICATE", "سامانه مصرف‌کننده‌ای با همین کد قبلاً ثبت شده است.")
    api_key = "pyk_" + secrets.token_urlsafe(32)
    client = ServiceClient(tenant_id=tenant_id, code=code, title=data.get("title") or code,
                           api_key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
                           api_key_masked=api_key[:8] + "…" + api_key[-4:],
                           scopes=list(data.get("scopes") or []),
                           created_by=actor.audit_id(), note=data.get("note"))
    db.add(client)
    db.flush()
    out = _client_out(client)
    out["api_key"] = api_key  # فقط همین یک بار
    return out


def revoke_service_client(db: Session, tenant_id, client_id) -> dict:
    client = db.execute(select(ServiceClient).where(
        ServiceClient.tenant_id == tenant_id, ServiceClient.id == client_id)).scalar_one_or_none()
    if client is None:
        raise not_found("سامانه مصرف‌کننده یافت نشد.")
    client.status = "revoked"
    db.flush()
    return _client_out(client)


def list_service_clients(db: Session, tenant_id) -> list[dict]:
    rows = db.execute(select(ServiceClient).where(
        ServiceClient.tenant_id == tenant_id).order_by(ServiceClient.created_at.desc())).scalars().all()
    return [_client_out(c) for c in rows]


def _client_out(c: ServiceClient) -> dict:
    return {"id": str(c.id), "code": c.code, "title": c.title,
            "api_key_masked": c.api_key_masked, "scopes": c.scopes or [],
            "status": c.status, "last_seen_at": c.last_seen_at,
            "last_seen_at_jalali": c.last_seen_at_jalali,
            "note": c.note, "created_at": c.created_at}


# ---------- درج دستی و همگام‌سازی اساتید ----------

_INSTRUCTOR_KEYS = {
    "source_code": ("id", "code", "source_code", "instructor_id", "professor_id", "کد", "شناسه"),
    "full_name": ("full_name", "name", "title", "instructor", "professor", "instructor_name",
                  "teacher", "teacher_name", "نام", "نام استاد", "نام‌ونام‌خانوادگی"),
    "rank": ("rank", "academic_rank", "grade", "مرتبه", "مرتبه علمی", "رتبه"),
    "department": ("department", "dept", "group", "faculty", "گروه", "دانشکده", "گروه آموزشی"),
    "email": ("email", "mail", "ایمیل"),
    "phone": ("phone", "mobile", "tel", "تلفن", "موبایل"),
}


def _norm_key(k: str) -> str:
    return re.sub(r"[\s_\-]+", " ", str(k).strip()).lower()


def _pick(row: dict, keys: tuple[str, ...]):
    lookup = {_norm_key(k): v for k, v in row.items()}
    for cand in keys:
        v = lookup.get(_norm_key(cand))
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return None


def _map_instructor(row: dict) -> dict | None:
    name = _pick(row, _INSTRUCTOR_KEYS["full_name"])
    code = _pick(row, _INSTRUCTOR_KEYS["source_code"]) or name
    if not name:
        return None
    return {"source_code": code or name, "full_name": name,
            "rank": _pick(row, _INSTRUCTOR_KEYS["rank"]),
            "department": _pick(row, _INSTRUCTOR_KEYS["department"]),
            "email": _pick(row, _INSTRUCTOR_KEYS["email"]),
            "phone": _pick(row, _INSTRUCTOR_KEYS["phone"]),
            "extra": {k: v for k, v in row.items()
                      if k not in sum(_INSTRUCTOR_KEYS.values(), ())}}


_CLASSROOM_KEYS = {
    "source_code": ("id", "code", "source_code", "room_id", "room_code", "کد", "شناسه"),
    "name": ("name", "title", "room_name", "room", "classroom", "hall", "نام", "نام کلاس", "عنوان"),
    "kind": ("kind", "type", "room_type", "class_type", "نوع", "نوع فضا"),
    "building": ("building", "location", "site", "ساختمان", "محل", "موقعیت"),
    "capacity": ("capacity", "cap", "size", "ظرفیت", "گنجایش"),
}


def _map_classroom(row: dict) -> dict | None:
    name = _pick(row, _CLASSROOM_KEYS["name"])
    code = _pick(row, _CLASSROOM_KEYS["source_code"]) or name
    if not name:
        return None
    cap = _pick(row, _CLASSROOM_KEYS["capacity"])
    try:
        cap_i = int(re.sub(r"\D", "", cap)) if cap else None
    except ValueError:
        cap_i = None
    return {"source_code": code or name, "name": name,
            "kind": _pick(row, _CLASSROOM_KEYS["kind"]),
            "building": _pick(row, _CLASSROOM_KEYS["building"]),
            "capacity": cap_i,
            "extra": {k: v for k, v in row.items()
                      if k not in sum(_CLASSROOM_KEYS.values(), ())}}


def _upsert(db: Session, model, tenant_id, source: str, mapped: list[dict]) -> dict:
    created, updated = 0, 0
    for m in mapped:
        code = m["source_code"]
        row = db.execute(select(model).where(
            model.tenant_id == tenant_id, model.source_code == code)).scalar_one_or_none()
        if row is None:
            db.add(model(tenant_id=tenant_id, source=source, **m))
            created += 1
        else:
            for k, v in m.items():
                if k != "source_code":
                    setattr(row, k, v)
            row.source = source
            updated += 1
    db.flush()
    return {"created": created, "updated": updated, "total": created + updated}


def import_instructors(db: Session, tenant_id, actor: Actor, items: list[dict], source: str = "manual") -> dict:
    mapped = [m for m in (_map_instructor(r) for r in items) if m]
    skipped = len(items) - len(mapped)
    if not mapped:
        raise conflict("NO_VALID_ROWS", "هیچ ردیف معتبری (با نام استاد) پیدا نشد؛ کلیدهای پذیرفته: نام/name/instructor…")
    counts = _upsert(db, Instructor, tenant_id, source, mapped)
    log_fetch(db, tenant_id, direction="in", domain="instructors", source=source,
              endpoint="masterdata/import/instructors", record_count=counts["total"],
              error=f"رد {skipped} ردیف بدون نام" if skipped else None)
    return {**counts, "skipped": skipped}


def import_classrooms(db: Session, tenant_id, actor: Actor, items: list[dict], source: str = "manual") -> dict:
    mapped = [m for m in (_map_classroom(r) for r in items) if m]
    skipped = len(items) - len(mapped)
    if not mapped:
        raise conflict("NO_VALID_ROWS", "هیچ ردیف معتبری (با نام کلاس/سالن) پیدا نشد؛ کلیدهای پذیرفته: نام/name/room…")
    counts = _upsert(db, Classroom, tenant_id, source, mapped)
    log_fetch(db, tenant_id, direction="in", domain="classrooms", source=source,
              endpoint="masterdata/import/classrooms", record_count=counts["total"],
              error=f"رد {skipped} ردیف بدون نام" if skipped else None)
    return {**counts, "skipped": skipped}


# ---------- همگام‌سازی خودکار از منابع خارجی ----------

def _extract_json_items(payload) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("instructors", "rooms", "items", "data", "results", "records"):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def _extract_html_rows(html: str) -> list[dict]:
    """پارس محتاط جدول HTML صفحات admin (وقتی JSON نداریم) — ردیف‌های <tr> با سلول‌های <td>."""
    rows: list[dict] = []
    header: list[str] = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = [re.sub(r"<[^>]+>", " ", c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        cells = [re.sub(r"\s+", " ", c).strip() for c in cells]
        if not cells:
            continue
        if any(re.search(r"<t[h]", tr, re.I) for _ in [0]) or not header and len(cells) > 1:
            if not header and ("نام" in " ".join(cells) or "کد" in " ".join(cells)):
                header = cells
                continue
        if header and len(cells) == len(header):
            rows.append(dict(zip(header, cells)))
        elif len(cells) >= 2:
            rows.append({"code": cells[0], "name": cells[1]})
    return rows


def sync_instructors_from_source(db: Session, tenant_id, actor: Actor) -> dict:
    """واکشی خودکار از darsyar360 — با کوکی ادمین یا endpoint JSON؛ در نبود پیکربندی خطای شفاف."""
    base = settings.DARSYAR_BASE.rstrip("/")
    headers = {"User-Agent": "PayehYar360-core/1.0"}
    cookie = settings.DARSYAR_ADMIN_COOKIE
    url_json = settings.DARSYAR_INSTRUCTORS_JSON_URL
    if not cookie and not url_json:
        raise conflict(
            "SOURCE_NOT_CONFIGURED",
            "واکشی خودکار اساتید نیازمند پیکربندی منبع است: متغیر DARSYAR_ADMIN_COOKIE "
            "(کوکی مرورگر با دسترسی admin در darsyar360.ir) یا DARSYAR_INSTRUCTORS_JSON_URL تنظیم شود؛ "
            "تا آن زمان از «درج دستی» استفاده کنید.")
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=settings.EXTERNAL_HTTP_TIMEOUT, follow_redirects=True) as hc:
            if url_json:
                resp = hc.get(url_json, headers=headers)
            else:
                resp = hc.get(f"{base}/admin/instructors", headers={**headers, "Cookie": cookie})
            duration = int((time.monotonic() - t0) * 1000)
            if resp.status_code in (301, 302, 303, 307) or "login" in str(resp.url):
                log_fetch(db, tenant_id, direction="in", domain="instructors", source="darsyar360",
                          record_count=0, status="failed", http_status=resp.status_code,
                          duration_ms=duration, error="redirect_to_login — کوکی منقضی/نامعتبر است")
                db.commit()
                raise conflict("SOURCE_AUTH_FAILED", "منبع ما را به صفحه ورود فرستاد؛ کوکی ادمین منقضی یا نامعتبر است.")
            if resp.status_code != 200:
                log_fetch(db, tenant_id, direction="in", domain="instructors", source="darsyar360",
                          record_count=0, status="failed", http_status=resp.status_code,
                          duration_ms=duration, error=resp.text[:300])
                db.commit()
                raise conflict("SOURCE_UNAVAILABLE", f"منبع پاسخ {resp.status_code} داد.")
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                raw = _extract_json_items(resp.json())
            else:
                raw = _extract_html_rows(resp.text)
            mapped = [m for m in (_map_instructor(r) for r in raw) if m]
            if not mapped:
                log_fetch(db, tenant_id, direction="in", domain="instructors", source="darsyar360",
                          record_count=0, status="failed", http_status=200, duration_ms=duration,
                          error="no rows parsed — ساختار صفحه تغییر کرده یا جدول خالی است")
                db.commit()
                raise conflict("SOURCE_EMPTY", "از پاسخ منبع هیچ استاد قابل استخراج نبود.")
            counts = _upsert(db, Instructor, tenant_id, "darsyar360", mapped)
            log_fetch(db, tenant_id, direction="in", domain="instructors", source="darsyar360",
                      record_count=counts["total"], http_status=200, duration_ms=duration)
            db.commit()
            return {**counts, "source": "darsyar360"}
    except httpx.HTTPError as exc:
        log_fetch(db, tenant_id, direction="in", domain="instructors", source="darsyar360",
                  status="failed", error=str(exc)[:300])
        db.commit()
        raise conflict("SOURCE_UNREACHABLE", f"ارتباط با منبع ناموفق بود: {exc}") from exc


def sync_classrooms_from_source(db: Session, tenant_id, actor: Actor) -> dict:
    """واکشی خودکار از سامانه برنامه‌ریزی درسی (8083): POST /api/auth/login سپس GET rooms/list."""
    base = settings.SCHEDULER_BASE.rstrip("/")
    if not settings.SCHEDULER_USERNAME or not settings.SCHEDULER_PASSWORD:
        raise conflict(
            "SOURCE_NOT_CONFIGURED",
            "واکشی خودکار کلاس‌ها/سالن‌ها نیازمند SCHEDULER_USERNAME و SCHEDULER_PASSWORD "
            f"(کاربر دارای دسترسی در {base}) است؛ تا آن زمان از «درج دستی» استفاده کنید.")
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=settings.EXTERNAL_HTTP_TIMEOUT, follow_redirects=True) as hc:
            login = hc.post(f"{base}/api/auth/login",
                            json={"username": settings.SCHEDULER_USERNAME,
                                  "password": settings.SCHEDULER_PASSWORD})
            duration = int((time.monotonic() - t0) * 1000)
            if login.status_code != 200:
                log_fetch(db, tenant_id, direction="in", domain="classrooms", source="scheduler8083",
                          status="failed", http_status=login.status_code, duration_ms=duration,
                          error="login failed: " + login.text[:200])
                db.commit()
                raise conflict("SOURCE_AUTH_FAILED", "ورود به سامانه برنامه‌ریزی ناموفق بود؛ نام کاربری/رمز را بررسی کنید.")
            token = (login.json() or {}).get("access_token")
            resp = hc.get(f"{base}/api/professors-rooms/rooms/list",
                          headers={"Authorization": f"Bearer {token}"})
            duration = int((time.monotonic() - t0) * 1000)
            if resp.status_code != 200:
                log_fetch(db, tenant_id, direction="in", domain="classrooms", source="scheduler8083",
                          status="failed", http_status=resp.status_code, duration_ms=duration,
                          error=resp.text[:300])
                db.commit()
                raise conflict("SOURCE_UNAVAILABLE", f"rooms/list پاسخ {resp.status_code} داد.")
            raw = _extract_json_items(resp.json())
            mapped = [m for m in (_map_classroom(r) for r in raw) if m]
            if not mapped:
                log_fetch(db, tenant_id, direction="in", domain="classrooms", source="scheduler8083",
                          status="failed", http_status=200, duration_ms=duration,
                          error="no rows parsed — ساختار پاسخ تغییر کرده یا خالی است")
                db.commit()
                raise conflict("SOURCE_EMPTY", "از پاسخ منبع هیچ کلاس/سالنی قابل استخراج نبود.")
            counts = _upsert(db, Classroom, tenant_id, "scheduler8083", mapped)
            log_fetch(db, tenant_id, direction="in", domain="classrooms", source="scheduler8083",
                      record_count=counts["total"], http_status=200, duration_ms=duration)
            db.commit()
            return {**counts, "source": "scheduler8083"}
    except httpx.HTTPError as exc:
        log_fetch(db, tenant_id, direction="in", domain="classrooms", source="scheduler8083",
                  status="failed", error=str(exc)[:300])
        db.commit()
        raise conflict("SOURCE_UNREACHABLE", f"ارتباط با سامانه برنامه‌ریزی ناموفق بود: {exc}") from exc


# ---------- کاتالوگ و تاریخچه ----------

def _last_log(db: Session, tenant_id, domain: str, direction: str) -> FetchLog | None:
    return db.execute(select(FetchLog).where(
        FetchLog.tenant_id == tenant_id, FetchLog.domain == domain,
        FetchLog.direction == direction).order_by(FetchLog.occurred_at.desc()).limit(1)).scalar_one_or_none()


def catalog(db: Session, tenant_id) -> dict:
    """کاتالوگ سرویس‌ها برای سایر سامانه‌ها: دامنه‌ها، شمارش، آخرین بروزرسانی/واکشی (شمسی)."""
    base = "/api/v1/services/masterdata/"
    instructors_count = db.execute(select(func.count()).select_from(Instructor).where(
        Instructor.tenant_id == tenant_id, Instructor.status == "active")).scalar() or 0
    classrooms_count = db.execute(select(func.count()).select_from(Classroom).where(
        Classroom.tenant_id == tenant_id, Classroom.status == "active")).scalar() or 0
    org_count = db.execute(select(func.count()).select_from(Organization).where(
        Organization.tenant_id == tenant_id)).scalar() or 0
    sets = {str(s.id): s.code for s in db.execute(select(ReferenceSet).where(
        ReferenceSet.tenant_id == tenant_id)).scalars().all()}
    course_ids = [uuid.UUID(sid) for sid, code in sets.items() if code == "unique_courses"]
    course_count = 0
    if course_ids:
        course_count = db.execute(select(func.count()).select_from(ReferenceItem).where(
            ReferenceItem.tenant_id == tenant_id, ReferenceItem.set_id.in_(course_ids))).scalar() or 0
    ref_count = db.execute(select(func.count()).select_from(ReferenceItem).where(
        ReferenceItem.tenant_id == tenant_id)).scalar() or 0
    syllabi_count = db.execute(select(func.count()).select_from(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant_id, CourseSyllabus.status == "active")).scalar() or 0
    counts = {"instructors": instructors_count, "classrooms": classrooms_count,
              "organizations": org_count, "unique-courses": course_count,
              "course-syllabi": syllabi_count, "reference-items": ref_count}
    items = []
    for domain, (title, _prov) in SERVICE_DOMAINS.items():
        last_in = _last_log(db, tenant_id, domain, "in")
        last_out = _last_log(db, tenant_id, domain, "out")
        configured = True
        if domain == "instructors":
            configured = bool(settings.DARSYAR_ADMIN_COOKIE or settings.DARSYAR_INSTRUCTORS_JSON_URL)
        elif domain == "classrooms":
            configured = bool(settings.SCHEDULER_USERNAME and settings.SCHEDULER_PASSWORD)
        items.append({
            "domain": domain, "title": title, "endpoint": base + domain,
            "count": counts.get(domain, 0), "source_configured": configured,
            "last_sync": {"at": last_in.occurred_at, "at_jalali": last_in.occurred_at_jalali,
                          "source": last_in.source, "status": last_in.status,
                          "count": last_in.record_count} if last_in else None,
            "last_fetch": {"at": last_out.occurred_at, "at_jalali": last_out.occurred_at_jalali,
                           "client": last_out.client_code, "status": last_out.status,
                           "count": last_out.record_count} if last_out else None,
        })
    return {"items": items}


def list_logs(db: Session, tenant_id, direction: str | None, domain: str | None, limit: int = 100) -> list[dict]:
    stmt = select(FetchLog).where(FetchLog.tenant_id == tenant_id)
    if direction:
        stmt = stmt.where(FetchLog.direction == direction)
    if domain:
        stmt = stmt.where(FetchLog.domain == domain)
    rows = db.execute(stmt.order_by(FetchLog.occurred_at.desc()).limit(limit)).scalars().all()
    return [{"id": str(r.id), "direction": r.direction, "domain": r.domain,
             "client_code": r.client_code, "source": r.source, "endpoint": r.endpoint,
             "record_count": r.record_count, "status": r.status,
             "http_status": r.http_status, "duration_ms": r.duration_ms,
             "error": r.error, "occurred_at": r.occurred_at,
             "occurred_at_jalali": r.occurred_at_jalali} for r in rows]


def list_instructors(db: Session, tenant_id, search: str | None, limit: int = 500) -> list[dict]:
    stmt = select(Instructor).where(Instructor.tenant_id == tenant_id)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(Instructor.full_name.ilike(like) |
                          Instructor.source_code.ilike(like) |
                          Instructor.department.ilike(like))
    rows = db.execute(stmt.order_by(Instructor.full_name).limit(limit)).scalars().all()
    return [{"id": str(i.id), "source_code": i.source_code, "full_name": i.full_name,
             "rank": i.rank, "department": i.department, "email": i.email, "phone": i.phone,
             "status": i.status, "source": i.source,
             "updated_at": i.updated_at, "updated_at_jalali": jalali_str(i.updated_at, with_time=True)}
            for i in rows]


def list_classrooms(db: Session, tenant_id, search: str | None, limit: int = 500) -> list[dict]:
    stmt = select(Classroom).where(Classroom.tenant_id == tenant_id)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(Classroom.name.ilike(like) |
                          Classroom.source_code.ilike(like) |
                          Classroom.building.ilike(like))
    rows = db.execute(stmt.order_by(Classroom.name).limit(limit)).scalars().all()
    return [{"id": str(c.id), "source_code": c.source_code, "name": c.name, "kind": c.kind,
             "building": c.building, "capacity": c.capacity, "status": c.status,
             "source": c.source, "updated_at": c.updated_at,
             "updated_at_jalali": jalali_str(c.updated_at, with_time=True)}
            for c in rows]


# ---------- سرفصل‌های مصوب دروس (course-syllabi) ----------

def _as_int(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _syllabus_fields(row: dict) -> dict:
    return {
        "title_fa": (str(row.get("title_fa")).strip() or None) if row.get("title_fa") else None,
        "title_en": str(row.get("title_en")).strip(),
        "course_code": (str(row.get("course_code")).strip() or None) if row.get("course_code") else None,
        "course_type": (str(row.get("course_type")).strip() or None) if row.get("course_type") else None,
        "unit_theory": _as_int(row.get("unit_theory")),
        "unit_practice": _as_int(row.get("unit_practice")),
        "hour_theory": _as_int(row.get("hour_theory")),
        "hour_practice": _as_int(row.get("hour_practice")),
        "prerequisites": row.get("prerequisites"),
        "corequisites": row.get("corequisites"),
        "general_goal": row.get("general_goal"),
        "evaluation": row.get("evaluation"),
        "references": row.get("references"),
        "has_text": bool(row.get("has_text", True)),
        "extra": row.get("extra") if isinstance(row.get("extra"), dict) else None,
        "raw_text": row.get("raw_text") or None,
    }


def import_syllabi(db: Session, tenant_id, actor: Actor, items: list[dict],
                   source: str = "manual") -> dict:
    """درج/بروزرسانی سرفصل‌ها — یکتایی بر (tenant, مجموعه, فایل منبع)؛ سرفصل‌ها بازنویسی می‌شوند."""
    created = updated = skipped = 0
    for row in items:
        if not isinstance(row, dict):
            skipped += 1
            continue
        title_en = str(row.get("title_en") or "").strip()
        if not title_en:
            title_en = str(row.get("title_fa") or "").strip()  # فال‌بک: عنوان فارسی
        if not title_en:
            skipped += 1
            continue
        sset = str(row.get("source_set") or "MANUAL").strip() or "MANUAL"
        sfile = str(row.get("source_file") or title_en).strip()
        fields = _syllabus_fields(row)
        row_db = db.execute(select(CourseSyllabus).where(
            CourseSyllabus.tenant_id == tenant_id,
            CourseSyllabus.source_set == sset,
            CourseSyllabus.source_file == sfile)).scalar_one_or_none()
        if row_db is None:
            row_db = CourseSyllabus(tenant_id=tenant_id, source_set=sset, source_file=sfile,
                                    source=source, **fields)
            db.add(row_db)
            created += 1
        else:
            for k, v in fields.items():
                setattr(row_db, k, v)
            row_db.source = source
            updated += 1
        db.flush()

        topics = [t for t in (row.get("topics") or []) if isinstance(t, dict) and str(t.get("title") or "").strip()]
        db.execute(delete(CourseSyllabusTopic).where(CourseSyllabusTopic.syllabus_id == row_db.id))
        for idx, t in enumerate(topics, start=1):
            db.add(CourseSyllabusTopic(
                syllabus_id=row_db.id, seq=_as_int(t.get("seq")) or idx,
                title=str(t.get("title")).strip(),
                hours=_as_int(t.get("hours")), hours_practice=_as_int(t.get("hours_practice"))))
    db.flush()
    total = created + updated
    if total:
        log_fetch(db, tenant_id, direction="in", domain="course-syllabi", source=source,
                  endpoint="masterdata/import/syllabi", record_count=total,
                  error=f"رد {skipped} ردیف بدون عنوان انگلیسی" if skipped else None)
    return {"created": created, "updated": updated, "total": total, "skipped": skipped}


def list_syllabi(db: Session, tenant_id, search: str | None, source_set: str | None,
                 limit: int = 500) -> list[dict]:
    stmt = select(CourseSyllabus).where(CourseSyllabus.tenant_id == tenant_id)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(CourseSyllabus.title_fa.ilike(like) |
                          CourseSyllabus.title_en.ilike(like) |
                          CourseSyllabus.course_code.ilike(like))
    if source_set:
        stmt = stmt.where(CourseSyllabus.source_set == source_set)
    rows = db.execute(stmt.order_by(CourseSyllabus.source_set, CourseSyllabus.title_en)
                      .limit(limit)).scalars().all()
    tcount = dict(db.execute(
        select(CourseSyllabusTopic.syllabus_id, func.count()).group_by(
            CourseSyllabusTopic.syllabus_id)).all())
    return [{"id": str(s.id), "source_set": s.source_set, "source_file": s.source_file,
             "title_fa": s.title_fa, "title_en": s.title_en, "course_code": s.course_code,
             "course_type": s.course_type, "unit_theory": s.unit_theory,
             "unit_practice": s.unit_practice, "hour_theory": s.hour_theory,
             "hour_practice": s.hour_practice, "has_text": s.has_text,
             "status": s.status, "topics_count": tcount.get(s.id, 0),
             "updated_at": s.updated_at,
             "updated_at_jalali": jalali_str(s.updated_at, with_time=True)}
            for s in rows]


def get_syllabus(db: Session, tenant_id, syllabus_id) -> dict:
    row = db.execute(select(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant_id, CourseSyllabus.id == syllabus_id)).scalar_one_or_none()
    if row is None:
        raise not_found("سرفصل یافت نشد.")
    topics = db.execute(select(CourseSyllabusTopic).where(
        CourseSyllabusTopic.syllabus_id == row.id).order_by(CourseSyllabusTopic.seq)).scalars().all()
    return {
        "id": str(row.id), "source_set": row.source_set, "source_file": row.source_file,
        "title_fa": row.title_fa, "title_en": row.title_en, "course_code": row.course_code,
        "course_type": row.course_type, "unit_theory": row.unit_theory,
        "unit_practice": row.unit_practice, "hour_theory": row.hour_theory,
        "hour_practice": row.hour_practice, "prerequisites": row.prerequisites,
        "corequisites": row.corequisites, "general_goal": row.general_goal,
        "evaluation": row.evaluation, "references": row.references,
        "has_text": row.has_text, "status": row.status, "source": row.source,
        "extra": row.extra or {}, "raw_text": row.raw_text,
        "topics": [{"seq": t.seq, "title": t.title, "hours": t.hours,
                    "hours_practice": t.hours_practice} for t in topics],
        "updated_at": row.updated_at, "updated_at_jalali": jalali_str(row.updated_at, with_time=True),
    }


def syllabi_stats(db: Session, tenant_id) -> dict:
    sets = dict(db.execute(
        select(CourseSyllabus.source_set, func.count()).where(
            CourseSyllabus.tenant_id == tenant_id).group_by(CourseSyllabus.source_set)).all())
    topics_count = db.execute(
        select(func.count()).select_from(CourseSyllabusTopic).join(
            CourseSyllabus, CourseSyllabusTopic.syllabus_id == CourseSyllabus.id).where(
            CourseSyllabus.tenant_id == tenant_id)).scalar() or 0
    scanned = db.execute(select(func.count()).select_from(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant_id, CourseSyllabus.has_text.is_(False))).scalar() or 0
    return {"total": sum(sets.values()), "by_set": {k: sets[k] for k in sorted(sets)},
            "topics_total": topics_count, "scanned_without_text": scanned,
            "sets_labels": SYLLABI_SETS}


def delete_syllabus_set(db: Session, tenant_id, actor: Actor, source_set: str) -> dict:
    """حذف کامل یک مجموعه سرفصل (مثلاً نسخه ناقص/اسکن‌شده) به‌همراه سرفصل‌هایش — برای ایمپورت مجدد."""
    sset = (source_set or "").strip()
    if not sset:
        raise not_found("مجموعه مشخص نشده است.")
    syl_ids = [r for r in db.execute(select(CourseSyllabus.id).where(
        CourseSyllabus.tenant_id == tenant_id,
        CourseSyllabus.source_set == sset)).scalars().all()]
    if not syl_ids:
        raise not_found(f"مجموعه «{sset}» یافت نشد.")
    del_topics = db.execute(delete(CourseSyllabusTopic).where(
        CourseSyllabusTopic.syllabus_id.in_(syl_ids)))
    del_syl = db.execute(delete(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant_id, CourseSyllabus.source_set == sset))
    db.flush()
    log_fetch(db, tenant_id, direction="in", domain="course-syllabi", source="manual",
              endpoint=f"masterdata/syllabi/set/{sset}",
              record_count=int(del_syl.rowcount or 0),
              error=f"حذف {int(del_topics.rowcount or 0)} سرفصل همراه سندها")
    return {"source_set": sset, "deleted_syllabi": int(del_syl.rowcount or 0),
            "deleted_topics": int(del_topics.rowcount or 0)}


SYLLABUS_EDITABLE = ("title_fa", "title_en", "course_code", "course_type",
                     "unit_theory", "unit_practice", "hour_theory", "hour_practice",
                     "prerequisites", "corequisites", "general_goal", "evaluation",
                     "references")
SYLLABUS_INT_FIELDS = ("unit_theory", "unit_practice", "hour_theory", "hour_practice")


def update_syllabus(db: Session, tenant_id, actor: Actor, syllabus_id, data: dict,
                    request: Request | None = None) -> dict:
    """ویرایش سرفصل مصوب (مدیر سامانه/نگهبان/ویرایشگر) — فیلدها + بازنویسی اختیاری ریز محتوا.

    ویرایش دستی یعنی داده اکنون مرتب‌شده است: برچسب has_text (اسکن بدون متن) برداشته می‌شود
    و updated_at برای همگام‌سازی دلتایی سایر سامانه‌ها به‌روز می‌شود.
    """
    row = db.execute(select(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant_id, CourseSyllabus.id == syllabus_id)).scalar_one_or_none()
    if row is None:
        raise not_found("سرفصل یافت نشد.")
    before = get_syllabus(db, tenant_id, syllabus_id)
    changed: list[str] = []
    for k in SYLLABUS_EDITABLE:
        if k not in data:
            continue
        v = data[k]
        if k in SYLLABUS_INT_FIELDS:
            v = _as_int(v)
        else:
            v = str(v).strip() if v is not None else None
            if not v:
                v = None
        if v != getattr(row, k):
            setattr(row, k, v)
            changed.append(k)
    if not (str(data.get("title_en") or "").strip() or row.title_en or "").strip():
        raise conflict("SYLLABUS_TITLE_REQUIRED", "عنوان انگلیسی خالی قابل ذخیره نیست — کلید تطبیق سرفصل است.")
    if data.get("topics") is not None:
        clean_topics = [t for t in data["topics"]
                        if isinstance(t, dict) and str(t.get("title") or "").strip()]
        db.execute(delete(CourseSyllabusTopic).where(CourseSyllabusTopic.syllabus_id == row.id))
        for idx, t in enumerate(clean_topics, start=1):
            db.add(CourseSyllabusTopic(
                syllabus_id=row.id, seq=_as_int(t.get("seq")) or idx,
                title=str(t["title"]).strip(),
                hours=_as_int(t.get("hours")), hours_practice=_as_int(t.get("hours_practice"))))
        changed.append("topics")
    if not changed:
        return before
    if row.has_text is False:
        row.has_text = True  # ویرایش دستی = داده مرتب‌شده؛ از گزارش «اسکن بدون متن» خارج می‌شود
    db.flush()
    after = get_syllabus(db, tenant_id, syllabus_id)
    log_fetch(db, tenant_id, direction="in", domain="course-syllabi", source="manual",
              endpoint="masterdata/syllabi", record_count=1,
              error=f"ویرایش سرفصل — فیلدها: {', '.join(changed)}")
    record_audit(db, tenant_id, actor, "syllabus.update", "course_syllabus", str(row.id),
                 before, after, request=request,
                 note=f"ویرایش سرفصل مصوب — فیلدها: {', '.join(changed)}")
    return after


def _syllabus_items(db: Session, tenant_id, since: str | None = None) -> list[dict]:
    stmt = select(CourseSyllabus).where(CourseSyllabus.tenant_id == tenant_id,
                                        CourseSyllabus.status == "active")
    if since:
        stmt = stmt.where(CourseSyllabus.updated_at > since)
    rows = db.execute(stmt.order_by(CourseSyllabus.source_set, CourseSyllabus.title_en)).scalars().all()
    ids = [r.id for r in rows]
    topics_by: dict = {}
    if ids:
        for t in db.execute(select(CourseSyllabusTopic).where(
                CourseSyllabusTopic.syllabus_id.in_(ids)).order_by(
                CourseSyllabusTopic.syllabus_id, CourseSyllabusTopic.seq)).scalars().all():
            topics_by.setdefault(t.syllabus_id, []).append(t)
    return [{"source_set": s.source_set, "source_file": s.source_file,
             "course_code": s.course_code, "title_fa": s.title_fa, "title_en": s.title_en,
             "course_type": s.course_type,
             "units": {"theory": s.unit_theory, "practice": s.unit_practice},
             "hours": {"theory": s.hour_theory, "practice": s.hour_practice},
             "prerequisites": s.prerequisites, "corequisites": s.corequisites,
             "general_goal": s.general_goal, "evaluation": s.evaluation,
             "references": s.references, "has_text": s.has_text,
             "topics": [{"seq": t.seq, "title": t.title, "hours": t.hours,
                         "hours_practice": t.hours_practice}
                        for t in topics_by.get(s.id, [])],
             "updated_at": s.updated_at}
            for s in rows]
