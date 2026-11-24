"""منطق اطلاعات پایه چندسامانه‌ای: همگام‌سازی از منابع خارجی، درج دستی، کاتالوگ سرویس و تاریخچه."""
from __future__ import annotations

import hashlib
import re
import secrets
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.common import statuses
from app.common.events import record_audit
from app.common.jalali import jalali_str
from app.core.config import settings
from app.core.errors import conflict, forbidden, not_found, unauthorized
from app.core.security import Actor
from app.modules.organizations.models import Organization
from app.modules.masterdata.models import (Classroom, CourseSyllabus, CourseSyllabusTopic,
                                           FetchLog, Instructor, ServiceClient, SplitCourse,
                                           UniqueCourse)
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


def _unique_course_items(db: Session, tenant_id, since: str | None = None) -> list[dict]:
    """درس‌های یکتا برای سایر سامانه‌ها — کد یکتا کلید مصرف‌کننده است."""
    stmt = select(UniqueCourse).where(UniqueCourse.tenant_id == tenant_id)
    if since:
        stmt = stmt.where(UniqueCourse.updated_at > since)
    return [{"set": "unique_courses", "code": u.code, "title": u.title_fa,
             "parent_code": None,
             "attrs": {"section": u.section, "unit_theory": u.unit_theory,
                       "unit_practice": u.unit_practice, "capacity": u.capacity,
                       "prerequisite": u.prerequisite, "source": u.source},
             "status": u.status, "updated_at": u.updated_at}
            for u in db.execute(stmt.order_by(UniqueCourse.code)).scalars().all()]


def _split_course_items(db: Session, tenant_id, since: str | None = None) -> list[dict]:
    """درس‌های تفکیکی برای سایر سامانه‌ها — کلید: (کد درس یکتا + سال + مجموعه).

    رفع باگ استقرار زنده (۲۰۲۶-۱۱-۲۳): در v1.0.12 عبارت ``order_by(uc.code, …)``
    داخل همان list comprehension نوشته شده بود؛ پایتون عبارت تکرارشونده را
    «قبل از» bind شدن متغیرهای حلقه (sc, uc) ارزیابی می‌کند و در نتیجه اولین
    واکشی این دامنه با ``NameError: name 'uc' is not defined`` (HTTP 500)
    شکست می‌خورد. ترتیب‌دهی اکنون با ویژگی‌های کلاس ORM پیش از اجرای کوئری است.
    """
    stmt = (select(SplitCourse, UniqueCourse).join(
        UniqueCourse, (UniqueCourse.id == SplitCourse.unique_course_id) &
        (UniqueCourse.tenant_id == SplitCourse.tenant_id)).where(
        SplitCourse.tenant_id == tenant_id)
        .order_by(UniqueCourse.code, SplitCourse.year_label.nullslast()))
    if since:
        stmt = stmt.where(SplitCourse.updated_at > since)
    return [{"set": "split_courses", "code": sc.code, "title": sc.title,
             "unique_course_code": uc.code, "unique_course_title": uc.title_fa,
             "parent_code": uc.code,
             "attrs": {"year_label": sc.year_label, "cohort_set": sc.cohort_set,
                       "unit_theory": sc.unit_theory, "unit_practice": sc.unit_practice,
                       "capacity": sc.capacity, "external_id": sc.external_id,
                       "source": sc.source},
             "status": sc.status, "updated_at": sc.updated_at}
            for sc, uc in db.execute(stmt).all()]


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


# نام‌های جایگزین دامنه که سایر سامانه‌ها ممکن است بخوانند (قرارداد مستند هم پوشش داده می‌شود)
_DOMAIN_ALIASES = {"syllabi": "course-syllabi"}


def _domain_etag(domain: str, items: list[dict]) -> str:
    """اثر انگشت وضعیت دامنه برای If-None-Match → 304 — بدون پرس‌وجوی اضافه.

    تغییر هر رکورد (یا تعداد آن‌ها) اثر انگشت را عوض می‌کند؛ سامانه مصرف‌کننده
    ETag را در درخواست بعدی با If-None-Match می‌فرستد و در صورت تطابق، بدنه
    (احتمالاً چندصدهزار بایت) منتقل نمی‌شود.
    """
    stamps = sorted(str(i.get("updated_at") or "") for i in items)
    src = f"{domain}|{len(items)}|{stamps[-1] if stamps else ''}"
    return '"' + hashlib.sha256(src.encode()).hexdigest()[:32] + '"'


def fetch_domain(db: Session, client: ServiceClient, domain: str, since: str | None,
                 endpoint: str, if_none_match: str | None = None) -> tuple[dict | None, str, str]:
    """واکشی یک دامنه برای کلاینت سرویس — خروجی: (payload یا None برای 304، etag، نام دامنه).

    - alias: «syllabi» همان «course-syllabi» سرویس داده می‌شود (هر دو نام معتبرند).
    - ETag: هدر If-None-Match مصرف‌کننده با اثر انگشت داده مقایسه می‌شود؛ تطابق =
      پاسخ 304 بدون انتقال بدنه (لاگ واکشی با items_returned=0 ثبت می‌گردد).
    """
    canonical = _DOMAIN_ALIASES.get(domain, domain)
    if canonical not in SERVICE_DOMAINS:
        raise not_found(f"دامنه «{domain}» تعریف نشده است؛ دامنه‌های معتبر: "
                        f"{', '.join(SERVICE_DOMAINS)} (نام جایگزین syllabi)")
    if client.scopes and canonical not in client.scopes:
        log_fetch(db, client.tenant_id, direction="out", domain=canonical, client_code=client.code,
                  client_id=client.id, endpoint=endpoint, status="failed", error="scope_not_allowed")
        db.commit()
        raise forbidden("SCOPE_FORBIDDEN", f"این کلید به دامنه «{canonical}» دسترسی ندارد.")
    t0 = time.monotonic()
    title, provider = SERVICE_DOMAINS[canonical]
    if canonical == "instructors":
        items = _instructor_items(db, client.tenant_id, since)
    elif canonical == "classrooms":
        items = _classroom_items(db, client.tenant_id, since)
    elif canonical == "organizations":
        items = _org_items(db, client.tenant_id)
    elif canonical == "unique-courses":
        items = _unique_course_items(db, client.tenant_id, since)
    elif canonical == "split-courses":
        items = _split_course_items(db, client.tenant_id, since)
    elif canonical == "course-syllabi":
        items = _syllabus_items(db, client.tenant_id, since)
    else:
        items = _ref_items(db, client.tenant_id, since)
    duration = int((time.monotonic() - t0) * 1000)
    etag = _domain_etag(canonical, items)
    if if_none_match and if_none_match.strip() == etag:
        # بدون تغییر — پاسخ 304: لاگ ثبت می‌شود ولی داده منتقل نمی‌شود
        _log_out(db, client, canonical, endpoint, 0, duration)
        db.commit()
        return None, etag, canonical
    now = datetime.now(timezone.utc)
    _log_out(db, client, canonical, endpoint, len(items), duration)
    db.commit()
    payload = {
        "ok": True, "domain": canonical, "title": title, "count": len(items),
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_jalali": jalali_str(now, with_time=True),
        "items": items,
    }
    if domain != canonical:
        payload["requested_domain"] = domain
    return payload, etag, canonical


SERVICE_DOMAINS: dict[str, tuple[str, str]] = {
    "instructors": ("اساتید", "masterdata"),
    "classrooms": ("کلاس‌ها و سالن‌ها", "masterdata"),
    "organizations": ("ساختار سازمانی", "core"),
    "unique-courses": ("درس‌های یکتا", "masterdata"),
    "split-courses": ("درس‌های تفکیکی", "masterdata"),
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
    uc_count = db.execute(select(func.count()).select_from(UniqueCourse).where(
        UniqueCourse.tenant_id == tenant_id)).scalar() or 0
    sc_count = db.execute(select(func.count()).select_from(SplitCourse).where(
        SplitCourse.tenant_id == tenant_id)).scalar() or 0
    ref_count = db.execute(select(func.count()).select_from(ReferenceItem).where(
        ReferenceItem.tenant_id == tenant_id)).scalar() or 0
    syllabi_count = db.execute(select(func.count()).select_from(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant_id, CourseSyllabus.status == "active")).scalar() or 0
    counts = {"instructors": instructors_count, "classrooms": classrooms_count,
              "organizations": org_count, "unique-courses": uc_count,
              "split-courses": sc_count,
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


def _chain_map(db: Session, tenant_id, sc_ids: set) -> dict:
    """نقشه زنجیره درس برای شناسه‌های درس تفکیکی: {split_id: (split, unique)}."""
    out = {}
    if not sc_ids:
        return out
    scs = db.execute(select(SplitCourse).where(
        SplitCourse.tenant_id == tenant_id, SplitCourse.id.in_(sc_ids))).scalars().all()
    uc_ids = {sc.unique_course_id for sc in scs}
    ucs = {u.id: u for u in db.execute(select(UniqueCourse).where(
        UniqueCourse.tenant_id == tenant_id, UniqueCourse.id.in_(uc_ids))).scalars().all()} if uc_ids else {}
    for sc in scs:
        out[sc.id] = (sc, ucs.get(sc.unique_course_id))
    return out


def _chain_out(sc: SplitCourse | None, uc: UniqueCourse | None) -> dict:
    if sc is None:
        return {"split_course": None, "unique_course": None}
    return {
        "split_course": {"id": str(sc.id), "code": sc.code, "title": sc.title,
                         "year_label": sc.year_label, "cohort_set": sc.cohort_set},
        "unique_course": ({"id": str(uc.id), "code": uc.code, "title_fa": uc.title_fa,
                           "section": uc.section} if uc else None),
    }


def list_syllabi(db: Session, tenant_id, search: str | None, source_set: str | None,
                 split_course_id: str | None = None, limit: int = 500) -> list[dict]:
    stmt = select(CourseSyllabus).where(CourseSyllabus.tenant_id == tenant_id)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(CourseSyllabus.title_fa.ilike(like) |
                          CourseSyllabus.title_en.ilike(like) |
                          CourseSyllabus.course_code.ilike(like))
    if source_set:
        stmt = stmt.where(CourseSyllabus.source_set == source_set)
    if split_course_id:
        try:
            stmt = stmt.where(CourseSyllabus.split_course_id == uuid.UUID(str(split_course_id)))
        except ValueError:
            raise not_found("شناسه درس تفکیکی نامعتبر است.")
    rows = db.execute(stmt.order_by(CourseSyllabus.source_set, CourseSyllabus.title_en)
                      .limit(limit)).scalars().all()
    tcount = dict(db.execute(
        select(CourseSyllabusTopic.syllabus_id, func.count()).group_by(
            CourseSyllabusTopic.syllabus_id)).all())
    chain = _chain_map(db, tenant_id, {s.split_course_id for s in rows if s.split_course_id})
    out = []
    for s in rows:
        sc, uc = chain.get(s.split_course_id, (None, None)) if s.split_course_id else (None, None)
        out.append({"id": str(s.id), "source_set": s.source_set, "source_file": s.source_file,
                    "title_fa": s.title_fa, "title_en": s.title_en, "course_code": s.course_code,
                    "course_type": s.course_type, "unit_theory": s.unit_theory,
                    "unit_practice": s.unit_practice, "hour_theory": s.hour_theory,
                    "hour_practice": s.hour_practice, "has_text": s.has_text,
                    "status": s.status, "topics_count": tcount.get(s.id, 0),
                    "updated_at": s.updated_at,
                    "updated_at_jalali": jalali_str(s.updated_at, with_time=True),
                    **_chain_out(sc, uc)})
    return out


def get_syllabus(db: Session, tenant_id, syllabus_id) -> dict:
    row = db.execute(select(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant_id, CourseSyllabus.id == syllabus_id)).scalar_one_or_none()
    if row is None:
        raise not_found("سرفصل یافت نشد.")
    topics = db.execute(select(CourseSyllabusTopic).where(
        CourseSyllabusTopic.syllabus_id == row.id).order_by(CourseSyllabusTopic.seq)).scalars().all()
    chain = _chain_out(*_chain_map(db, tenant_id, {row.split_course_id}).get(row.split_course_id, (None, None))
                       if row.split_course_id else (None, None))
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
        **chain,
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
    if "split_course_id" in data:
        sc_val = data.get("split_course_id")
        if sc_val in (None, "", "null"):
            if row.split_course_id is not None:
                row.split_course_id = None
                changed.append("split_course_id")
        else:
            sc = db.execute(select(SplitCourse).where(
                SplitCourse.tenant_id == tenant_id,
                SplitCourse.id == _as_uuid(sc_val))).scalar_one_or_none()
            if sc is None:
                raise not_found("درس تفکیکی یافت نشد.")
            if row.split_course_id != sc.id:
                row.split_course_id = sc.id
                changed.append("split_course_id")
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


# ---------- زنجیره درس: درس یکتا ← درس تفکیکی ← سرفصل مصوب ----------
# قاعده کسب‌وکار: هر درس یکتا ۱ تا ۳ درس تفکیکی دارد (تفکیک با سال یا مجموعه
# پیوسته/ناپیوسته) و هر درس تفکیکی سرفصل‌های مصوب خودش را دارد.

UC_FIELDS = ("code", "title_fa", "title_en", "section", "unit_theory", "unit_practice",
             "capacity", "prerequisite", "status")
SC_FIELDS = ("code", "title", "year_label", "cohort_set", "unit_theory", "unit_practice",
             "capacity", "status")
CHAIN_OK_COUNTS = (1, 3)


def _as_uuid(v) -> uuid.UUID | None:
    """تبدیل امن به UUID برای مقایسه با ستون‌های شناسه؛ نامعتبر → None."""
    try:
        return uuid.UUID(str(v))
    except (ValueError, AttributeError, TypeError):
        return None


def _norm_title(v) -> str:
    """نرمال‌سازی عنوان برای تطبیق زنجیره: یکدست‌سازی نیم‌فاصله و فاصله‌ها."""
    s = str(v or "").replace("\u200c", " ").replace("ي", "ی").replace("ك", "ک")
    return re.sub(r"\s+", " ", s).strip()


def _uc_out(db: Session, tenant_id, row: UniqueCourse, counts: dict | None = None) -> dict:
    if counts is None:
        counts = _uc_counts(db, tenant_id, [row.id])
    sp, sy = counts.get(str(row.id), (0, 0))
    return {"id": str(row.id), "code": row.code, "title_fa": row.title_fa, "title_en": row.title_en,
            "section": row.section, "unit_theory": row.unit_theory, "unit_practice": row.unit_practice,
            "capacity": row.capacity, "prerequisite": row.prerequisite, "status": row.status,
            "source": row.source, "extra": row.extra or {},
            "split_count": sp, "syllabi_count": sy,
            "chain_ok": sp in CHAIN_OK_COUNTS,
            "updated_at": row.updated_at,
            "updated_at_jalali": jalali_str(row.updated_at, with_time=True)}


def _uc_counts(db: Session, tenant_id, uc_ids: list) -> dict:
    """برای هر درس یکتا: (تعداد درس تفکیکی، تعداد سرفصل‌های متصل به تفکیکی‌ها)."""
    if not uc_ids:
        return {}
    ids = list(uc_ids)
    sp = dict(db.execute(
        select(SplitCourse.unique_course_id, func.count()).where(
            SplitCourse.tenant_id == tenant_id,
            SplitCourse.unique_course_id.in_(ids)).group_by(SplitCourse.unique_course_id)).all())
    sy_rows = db.execute(
        select(SplitCourse.unique_course_id, func.count()).join(
            CourseSyllabus, CourseSyllabus.split_course_id == SplitCourse.id).where(
            SplitCourse.tenant_id == tenant_id,
            SplitCourse.unique_course_id.in_(ids)).group_by(SplitCourse.unique_course_id)).all()
    sy = dict(sy_rows)
    return {str(k): (n, sy.get(k, 0)) for k, n in sp.items()} | \
           {str(k): (0, 0) for k in ids if k not in sp}


def list_unique_courses(db: Session, tenant_id, search: str | None = None,
                        section: str | None = None, status: str | None = None,
                        limit: int = 500, offset: int = 0) -> dict:
    stmt = select(UniqueCourse).where(UniqueCourse.tenant_id == tenant_id)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(UniqueCourse.title_fa.ilike(like) |
                          UniqueCourse.title_en.ilike(like) |
                          UniqueCourse.code.ilike(like))
    if section:
        stmt = stmt.where(UniqueCourse.section == section)
    if status:
        stmt = stmt.where(UniqueCourse.status == status)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(UniqueCourse.section, UniqueCourse.code)
                      .limit(limit).offset(offset)).scalars().all()
    counts = _uc_counts(db, tenant_id, [r.id for r in rows])
    return {"total": total, "items": [_uc_out(db, tenant_id, r, counts) for r in rows]}


def get_unique_course(db: Session, tenant_id, uc_id) -> dict:
    row = db.execute(select(UniqueCourse).where(
        UniqueCourse.tenant_id == tenant_id, UniqueCourse.id == uc_id)).scalar_one_or_none()
    if row is None:
        raise not_found("درس یکتا یافت نشد.")
    out = _uc_out(db, tenant_id, row)
    scs = db.execute(select(SplitCourse).where(
        SplitCourse.tenant_id == tenant_id, SplitCourse.unique_course_id == row.id)
        .order_by(SplitCourse.year_label.nullslast(), SplitCourse.cohort_set)).scalars().all()
    sc_ids = [sc.id for sc in scs]
    syc = dict(db.execute(
        select(CourseSyllabus.split_course_id, func.count()).where(
            CourseSyllabus.split_course_id.in_(sc_ids)).group_by(
            CourseSyllabus.split_course_id)).all()) if sc_ids else {}
    out["split_courses"] = [{"id": str(sc.id), "code": sc.code, "title": sc.title,
                             "year_label": sc.year_label, "cohort_set": sc.cohort_set,
                             "unit_theory": sc.unit_theory, "unit_practice": sc.unit_practice,
                             "capacity": sc.capacity, "status": sc.status,
                             "syllabi_count": syc.get(sc.id, 0),
                             "updated_at_jalali": jalali_str(sc.updated_at, with_time=True)}
                            for sc in scs]
    out["syllabi_total"] = sum(syc.values())
    out["chain_ok"] = len(scs) in CHAIN_OK_COUNTS
    return out


def _unique_course_by_id(db: Session, tenant_id, uc_id) -> UniqueCourse:
    row = db.execute(select(UniqueCourse).where(
        UniqueCourse.tenant_id == tenant_id,
        UniqueCourse.id == _as_uuid(uc_id))).scalar_one_or_none()
    if row is None:
        raise not_found("درس یکتا یافت نشد.")
    return row


def create_unique_course(db: Session, tenant_id, actor: Actor, data: dict,
                         request: Request | None = None) -> dict:
    code = str(data.get("code") or "").strip()
    title = _norm_title(data.get("title_fa"))
    if not code or not title:
        raise conflict("UC_CODE_TITLE_REQUIRED", "کد یکتا و عنوان فارسی درس الزامی است.")
    dup = db.execute(select(UniqueCourse).where(
        UniqueCourse.tenant_id == tenant_id, UniqueCourse.code == code)).scalar_one_or_none()
    if dup is not None:
        raise conflict("UC_DUPLICATE", f"درس یکتایی با کد «{code}» قبلاً ثبت شده است.")
    row = UniqueCourse(tenant_id=tenant_id, code=code, title_fa=title, source="manual",
                       **{k: data.get(k) for k in UC_FIELDS if k not in ("code", "title_fa") and data.get(k) is not None})
    db.add(row)
    db.flush()
    out = _uc_out(db, tenant_id, row)
    record_audit(db, tenant_id, actor, "unique_course.create", "unique_course", str(row.id),
                 None, out, request=request, note="درج دستی درس یکتا")
    return out


def update_unique_course(db: Session, tenant_id, actor: Actor, uc_id, data: dict,
                         request: Request | None = None) -> dict:
    row = _unique_course_by_id(db, tenant_id, uc_id)
    before = _uc_out(db, tenant_id, row)
    changed = []
    for k in UC_FIELDS:
        if k not in data:
            continue
        v = data[k]
        if k in ("unit_theory", "unit_practice", "capacity"):
            v = _as_int(v)
        elif isinstance(v, str):
            v = v.strip() or None
            if v is None and k in ("code", "title_fa", "status"):
                continue  # خالی‌کردن کد/عنوان/وضعیت مجاز نیست
        if k == "code" and v and v != row.code:
            dup = db.execute(select(UniqueCourse).where(
                UniqueCourse.tenant_id == tenant_id, UniqueCourse.code == v,
                UniqueCourse.id != row.id)).scalar_one_or_none()
            if dup is not None:
                raise conflict("UC_DUPLICATE", f"درس یکتایی با کد «{v}» قبلاً ثبت شده است.")
        if v != getattr(row, k):
            setattr(row, k, v)
            changed.append(k)
    db.flush()
    if not changed:
        return before
    after = _uc_out(db, tenant_id, row)
    record_audit(db, tenant_id, actor, "unique_course.update", "unique_course", str(row.id),
                 before, after, request=request,
                 note=f"ویرایش درس یکتا — فیلدها: {', '.join(changed)}")
    return after


def delete_unique_course(db: Session, tenant_id, actor: Actor, uc_id,
                         request: Request | None = None) -> dict:
    row = _unique_course_by_id(db, tenant_id, uc_id)
    sp_count = db.execute(select(func.count()).select_from(SplitCourse).where(
        SplitCourse.tenant_id == tenant_id, SplitCourse.unique_course_id == row.id)).scalar()
    if sp_count:
        raise conflict("UC_HAS_SPLITS",
                       f"این درس یکتا {sp_count} درس تفکیکی دارد — ابتدا آن‌ها را حذف کنید.")
    before = _uc_out(db, tenant_id, row)
    db.execute(delete(UniqueCourse).where(
        UniqueCourse.tenant_id == tenant_id, UniqueCourse.id == row.id))
    db.flush()
    record_audit(db, tenant_id, actor, "unique_course.delete", "unique_course", str(row.id),
                 before, None, request=request, note="حذف درس یکتا")
    return {"deleted": True, "code": row.code}


def _sc_out(db: Session, tenant_id, row: SplitCourse, syc: dict | None = None) -> dict:
    if syc is None:
        syc = {str(row.id): db.execute(select(func.count()).select_from(CourseSyllabus).where(
            CourseSyllabus.split_course_id == row.id)).scalar() or 0}
    return {"id": str(row.id), "unique_course_id": str(row.unique_course_id),
            "code": row.code, "title": row.title, "year_label": row.year_label,
            "cohort_set": row.cohort_set, "unit_theory": row.unit_theory,
            "unit_practice": row.unit_practice, "capacity": row.capacity,
            "status": row.status, "source": row.source, "external_id": row.external_id,
            "extra": row.extra or {}, "syllabi_count": syc.get(str(row.id), 0),
            "updated_at": row.updated_at,
            "updated_at_jalali": jalali_str(row.updated_at, with_time=True)}


def list_split_courses(db: Session, tenant_id, unique_course_id: str | None = None,
                       year: str | None = None, cohort: str | None = None,
                       search: str | None = None, status: str | None = None,
                       limit: int = 1000, offset: int = 0) -> dict:
    stmt = select(SplitCourse).where(SplitCourse.tenant_id == tenant_id)
    if unique_course_id:
        uc_uuid = _as_uuid(unique_course_id)
        if uc_uuid is None:
            raise not_found("شناسه درس یکتا نامعتبر است.")
        stmt = stmt.where(SplitCourse.unique_course_id == uc_uuid)
    if year:
        stmt = stmt.where(SplitCourse.year_label == year.strip())
    if cohort:
        stmt = stmt.where(SplitCourse.cohort_set == cohort.strip())
    if status:
        stmt = stmt.where(SplitCourse.status == status)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.join(UniqueCourse, UniqueCourse.id == SplitCourse.unique_course_id).where(
            SplitCourse.title.ilike(like) | UniqueCourse.title_fa.ilike(like) |
            UniqueCourse.code.ilike(like))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(SplitCourse.year_label.nullslast(), SplitCourse.cohort_set,
                                    SplitCourse.title)
                      .limit(limit).offset(offset)).scalars().all()
    syc = dict(db.execute(
        select(CourseSyllabus.split_course_id, func.count()).where(
            CourseSyllabus.split_course_id.in_([r.id for r in rows])).group_by(
            CourseSyllabus.split_course_id)).all()) if rows else {}
    syc = {str(k): v for k, v in syc.items()}
    uc_ids = {r.unique_course_id for r in rows}
    ucs = {u.id: u for u in db.execute(select(UniqueCourse).where(
        UniqueCourse.tenant_id == tenant_id, UniqueCourse.id.in_(uc_ids))).scalars().all()} if uc_ids else {}
    items = []
    for r in rows:
        uc = ucs.get(r.unique_course_id)
        items.append({**_sc_out(db, tenant_id, r, syc),
                      "unique_course": ({"id": str(uc.id), "code": uc.code,
                                         "title_fa": uc.title_fa, "section": uc.section}
                                        if uc else None)})
    return {"total": total, "items": items}


def get_split_course(db: Session, tenant_id, sc_id) -> dict:
    row = db.execute(select(SplitCourse).where(
        SplitCourse.tenant_id == tenant_id, SplitCourse.id == sc_id)).scalar_one_or_none()
    if row is None:
        raise not_found("درس تفکیکی یافت نشد.")
    out = _sc_out(db, tenant_id, row)
    uc = _unique_course_by_id(db, tenant_id, row.unique_course_id)
    out["unique_course"] = _uc_out(db, tenant_id, uc)
    syls = db.execute(select(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant_id,
        CourseSyllabus.split_course_id == row.id).order_by(CourseSyllabus.source_set)).scalars().all()
    out["syllabi"] = [{"id": str(s.id), "source_set": s.source_set, "title_fa": s.title_fa,
                       "title_en": s.title_en, "course_code": s.course_code,
                       "unit_theory": s.unit_theory, "unit_practice": s.unit_practice,
                       "updated_at_jalali": jalali_str(s.updated_at, with_time=True)} for s in syls]
    return out


def create_split_course(db: Session, tenant_id, actor: Actor, data: dict,
                        request: Request | None = None) -> dict:
    uc = _unique_course_by_id(db, tenant_id, data.get("unique_course_id"))
    title = _norm_title(data.get("title")) or uc.title_fa
    year_label = (str(data.get("year_label")).strip() or None) if data.get("year_label") else None
    cohort_set = (str(data.get("cohort_set")).strip() or None) if data.get("cohort_set") else None
    dup = db.execute(select(SplitCourse).where(
        SplitCourse.tenant_id == tenant_id, SplitCourse.unique_course_id == uc.id,
        SplitCourse.year_label == year_label, SplitCourse.cohort_set == cohort_set)).scalar_one_or_none()
    if dup is not None:
        raise conflict("SC_DUPLICATE",
                       "برای این درس یکتا، درس تفکیکی با همین سال/مجموعه قبلاً ثبت شده است.")
    row = SplitCourse(tenant_id=tenant_id, unique_course_id=uc.id, title=title,
                      year_label=year_label, cohort_set=cohort_set, source="manual",
                      **{k: data.get(k) for k in SC_FIELDS
                         if k not in ("title", "year_label", "cohort_set") and data.get(k) is not None})
    db.add(row)
    db.flush()
    out = _sc_out(db, tenant_id, row)
    record_audit(db, tenant_id, actor, "split_course.create", "split_course", str(row.id),
                 None, out, request=request, note="درج دستی درس تفکیکی")
    return out


def update_split_course(db: Session, tenant_id, actor: Actor, sc_id, data: dict,
                        request: Request | None = None) -> dict:
    row = db.execute(select(SplitCourse).where(
        SplitCourse.tenant_id == tenant_id, SplitCourse.id == _as_uuid(sc_id))).scalar_one_or_none()
    if row is None:
        raise not_found("درس تفکیکی یافت نشد.")
    before = _sc_out(db, tenant_id, row)
    changed = []
    if "unique_course_id" in data and str(data["unique_course_id"]) != str(row.unique_course_id):
        uc = _unique_course_by_id(db, tenant_id, data.get("unique_course_id"))
        row.unique_course_id = uc.id
        changed.append("unique_course_id")
    for k in SC_FIELDS:
        if k not in data:
            continue
        v = data[k]
        if k in ("unit_theory", "unit_practice", "capacity"):
            v = _as_int(v)
        elif k in ("code", "title", "year_label", "cohort_set", "status"):
            v = _norm_title(v) if k == "title" else (str(v).strip() if v is not None else None)
            if not v:
                v = None
        if v != getattr(row, k):
            setattr(row, k, v)
            changed.append(k)
    if {"unique_course_id", "year_label", "cohort_set"} & set(changed):
        dup = db.execute(select(SplitCourse).where(
            SplitCourse.tenant_id == tenant_id,
            SplitCourse.unique_course_id == row.unique_course_id,
            SplitCourse.year_label == row.year_label, SplitCourse.cohort_set == row.cohort_set,
            SplitCourse.id != row.id)).scalar_one_or_none()
        if dup is not None:
            raise conflict("SC_DUPLICATE",
                           "برای این درس یکتا، درس تفکیکی با همین سال/مجموعه قبلاً ثبت شده است.")
    db.flush()
    if not changed:
        return before
    after = _sc_out(db, tenant_id, row)
    record_audit(db, tenant_id, actor, "split_course.update", "split_course", str(row.id),
                 before, after, request=request,
                 note=f"ویرایش درس تفکیکی — فیلدها: {', '.join(changed)}")
    return after


def delete_split_course(db: Session, tenant_id, actor: Actor, sc_id,
                        request: Request | None = None) -> dict:
    row = db.execute(select(SplitCourse).where(
        SplitCourse.tenant_id == tenant_id, SplitCourse.id == _as_uuid(sc_id))).scalar_one_or_none()
    if row is None:
        raise not_found("درس تفکیکی یافت نشد.")
    before = _sc_out(db, tenant_id, row)
    n_syl = db.execute(select(func.count()).select_from(CourseSyllabus).where(
        CourseSyllabus.split_course_id == row.id)).scalar() or 0
    if n_syl:  # سرفصل‌های متصل جدا می‌شوند (حذف نمی‌شوند) و به‌عنوان بدون پیوند گزارش می‌شوند
        db.execute(update(CourseSyllabus).where(
            CourseSyllabus.split_course_id == row.id).values(split_course_id=None))
    db.execute(delete(SplitCourse).where(
        SplitCourse.tenant_id == tenant_id, SplitCourse.id == row.id))
    db.flush()
    record_audit(db, tenant_id, actor, "split_course.delete", "split_course", str(row.id),
                 before, None, request=request,
                 note=f"حذف درس تفکیکی — {n_syl} سرفصل از پیوند خارج شد")
    return {"deleted": True, "unlinked_syllabi": n_syl}


def upsert_darsyar_courses(db: Session, tenant_id, actor: Actor, rows: list[dict],
                           request: Request | None = None) -> dict:
    """ایمپورت ردیف‌های صفحه /admin/courses سامانه درس‌یار۳۶۰.

    هر ردیف یک «درس تفکیکی» است (کد یکتا + سال/مجموعه)؛ درس یکتا از کد یکتا ساخته
    و تکمیل می‌شود. ایمپورت مجدد همان داده بروزرسانی می‌کند (idempotent بر کلید منبع).
    """
    created_uc = updated_uc = created_sc = updated_sc = skipped = 0
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        code = str(row.get("unique_code") or "").strip()
        title = _norm_title(row.get("title"))
        if not code or not title:
            skipped += 1
            continue
        section = str(row.get("section") or "").strip() or None
        unit_theory, unit_practice = _as_int(row.get("unit_theory")), _as_int(row.get("unit_practice"))
        capacity = _as_int(row.get("capacity"))
        prereq = str(row.get("prereq") or "").strip() or None
        year_raw = str(row.get("year") or "").strip()
        cohort = str(row.get("type") or "").strip() or None
        year_label = year_raw if year_raw and year_raw != "ناپیوسته" else None
        if cohort is None and year_raw == "ناپیوسته":
            cohort = "ناپیوسته"
        external_id = str(row.get("external_id") or row.get("row") or "").strip() or None

        uc = db.execute(select(UniqueCourse).where(
            UniqueCourse.tenant_id == tenant_id, UniqueCourse.code == code)).scalar_one_or_none()
        if uc is None:
            uc = UniqueCourse(tenant_id=tenant_id, code=code, title_fa=title, section=section,
                              unit_theory=unit_theory, unit_practice=unit_practice,
                              capacity=capacity, prerequisite=prereq,
                              source="darsyar360", extra={"source_url": "darsyar360.ir/admin/courses"})
            db.add(uc)
            db.flush()
            created_uc += 1
        else:
            # تکمیل فیلدهای خالی از منبع — مقادیر ثبت‌شده دستی بازنویسی نمی‌شود
            if uc.section is None and section:
                uc.section = section
            if _norm_title(uc.title_fa) != title:
                uc.title_fa = title
            if uc.unit_theory is None and unit_theory is not None:
                uc.unit_theory = unit_theory
            if uc.unit_practice is None and unit_practice is not None:
                uc.unit_practice = unit_practice
            if uc.capacity is None and capacity is not None:
                uc.capacity = capacity
            if uc.prerequisite is None and prereq:
                uc.prerequisite = prereq
            if uc.source == "manual":
                uc.source = "darsyar360"
            updated_uc += 1
        db.flush()

        sc = db.execute(select(SplitCourse).where(
            SplitCourse.tenant_id == tenant_id, SplitCourse.unique_course_id == uc.id,
            SplitCourse.year_label == year_label, SplitCourse.cohort_set == cohort)).scalar_one_or_none()
        if sc is None:
            sc = SplitCourse(tenant_id=tenant_id, unique_course_id=uc.id, title=title,
                             year_label=year_label, cohort_set=cohort,
                             unit_theory=unit_theory, unit_practice=unit_practice,
                             capacity=capacity, source="darsyar360", external_id=external_id)
            db.add(sc)
            created_sc += 1
        else:
            if sc.title != title:
                sc.title = title
            if sc.unit_theory is None and unit_theory is not None:
                sc.unit_theory = unit_theory
            if sc.unit_practice is None and unit_practice is not None:
                sc.unit_practice = unit_practice
            if sc.capacity is None and capacity is not None:
                sc.capacity = capacity
            if sc.external_id is None:
                sc.external_id = external_id
            updated_sc += 1
    db.flush()
    total = created_uc + updated_uc + created_sc + updated_sc
    linked = link_syllabi_to_split_courses(db, tenant_id) if total else 0
    if total:
        log_fetch(db, tenant_id, direction="in", domain="unique-courses", source="darsyar360",
                  endpoint="darsyar360.ir/admin/courses", record_count=len(rows),
                  error=(f"رد {skipped} ردیف بدون کد/عنوان" if skipped else None))
        record_audit(db, tenant_id, actor, "unique_course.import", "unique_course", None,
                     None, {"rows": len(rows), "created_unique": created_uc,
                            "updated_unique": updated_uc, "created_split": created_sc,
                            "updated_split": updated_sc, "skipped": skipped,
                            "linked_syllabi": linked},
                     request=request, note="ایمپورت درس‌های تفکیکی از درس‌یار۳۶۰")
    return {"created_unique": created_uc, "updated_unique": updated_uc,
            "created_split": created_sc, "updated_split": updated_sc,
            "skipped": skipped, "linked_syllabi": linked}


def link_syllabi_to_split_courses(db: Session, tenant_id) -> int:
    """اتصال خودکار سرفصل‌های بدون پیوند به درس تفکیکی بر تطبیق عنوان.

    ترجیح سال بر اساس مجموعه سرفصل (۱۳۹۴ → سال ۱۳۹۴؛ CE403/NP1400 → سال ۱۴۰۳)؛
    در غیبت تطبیق هم‌سال، هر تطبیق عنوان پذیرفته می‌شود.
    """
    SET_YEAR = {"1394": "1394", "CE403": "1403", "NP1400": "1403"}
    syls = db.execute(select(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant_id,
        CourseSyllabus.split_course_id.is_(None))).scalars().all()
    if not syls:
        return 0
    scs = db.execute(select(SplitCourse).where(SplitCourse.tenant_id == tenant_id)).scalars().all()
    by_title: dict[str, list] = {}
    for sc in scs:
        by_title.setdefault(_norm_title(sc.title), []).append(sc)
    linked = 0
    for s in syls:
        candidates = by_title.get(_norm_title(s.title_fa)) or by_title.get(_norm_title(s.title_en)) or []
        if not candidates:
            continue
        pref = SET_YEAR.get(s.source_set)
        sc = next((c for c in candidates if c.year_label == pref), None) or \
            next((c for c in candidates if c.year_label), None) or candidates[0]
        s.split_course_id = sc.id
        linked += 1
    db.flush()
    return linked


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
