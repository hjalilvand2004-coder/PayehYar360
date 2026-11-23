"""موتور تحلیل کیفیت داده — داشبورد چندبعدی با drill-down تا ریشه مشکل.

ابعاد بررسی: کامل‌بودن، یکتایی، انسجام و مرجعیت، اعتبار، پوشش، به‌روزبودن
حوزه‌ها: اشخاص، سازمان‌ها، اطلاعات پایه، نگاشت شناسه

هر بررسی شامل: تعداد متأثر/کل، نرخ گذر وزنی، شدت، توضیح معنا، ریشه رایج و
راه اصلاح + ردیف‌های متأثر (نمونه تا سقف مشخص) تا کاربر بدون خروج از پنل
بتواند ریشه مشکل را پیدا کند.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common import statuses
from app.common.db import utcnow
from app.modules.identities.models import ExternalIdMapping
from app.modules.integrations.models import SystemInstallation
from app.modules.masterdata.models import CourseSyllabus, CourseSyllabusTopic
from app.modules.organizations.models import Organization
from app.modules.persons.models import Person, PersonIdentifier
from app.modules.references.models import ReferenceItem, ReferenceSet

WEIGHTS = {"high": 3, "medium": 2, "low": 1}
DETAIL_LIMIT = 50

DIMENSIONS = [
    ("completeness", "کامل‌بودن"),
    ("uniqueness", "یکتایی"),
    ("integrity", "انسجام و مرجعیت"),
    ("validity", "اعتبار"),
    ("coverage", "پوشش"),
    ("freshness", "به‌روزبودن"),
]
DOMAINS = [
    ("persons", "اشخاص"),
    ("organizations", "سازمان‌ها"),
    ("references", "اطلاعات پایه"),
    ("mappings", "نگاشت شناسه"),
    ("syllabi", "سرفصل دروس"),
]


class _Check:
    """یک بررسی کیفیت: شمارش متأثرین + ردیف‌های نمونه برای drill-down."""

    def __init__(self, check_id: str, dimension: str, domain: str, title: str,
                 severity: str, what: str, root_cause: str, fix_hint: str):
        self.check_id = check_id
        self.dimension = dimension
        self.domain = domain
        self.title = title
        self.severity = severity
        self.what = what
        self.root_cause = root_cause
        self.fix_hint = fix_hint
        self.total = 0
        self.affected = 0
        self.rows: list[dict] = []

    def set_total(self, total: int) -> None:
        self.total = total

    def hit(self, row: dict | None = None) -> None:
        self.affected += 1
        if row is not None and len(self.rows) < DETAIL_LIMIT:
            self.rows.append(row)

    def out(self) -> dict:
        rate = 1.0 if self.total == 0 else (self.total - self.affected) / self.total
        status = "ok" if self.affected == 0 else ("fail" if self.severity == "high" else "warn")
        return {
            "check_id": self.check_id, "dimension": self.dimension, "domain": self.domain,
            "title": self.title, "severity": self.severity, "status": status,
            "affected": self.affected, "total": self.total,
            "pass_rate": round(rate * 100, 1),
            "what": self.what, "root_cause": self.root_cause, "fix_hint": self.fix_hint,
            "rows": self.rows,
        }


def _s(v: str | None) -> str:
    return (v or "").strip()


def _run_person_checks(db: Session, tenant_id, checks: list[_Check]) -> None:
    persons = list(db.execute(select(Person).where(Person.tenant_id == tenant_id)).scalars().all())
    active = [p for p in persons if p.status == statuses.PERSON_ACTIVE]
    merged = [p for p in persons if p.status == statuses.PERSON_MERGED]
    pid_of = {str(p.id): p for p in persons}

    # ۱) کامل‌بودن اجزای نام
    c = _Check("persons_missing_name_parts", "completeness", "persons",
               "نام/نام‌خانوادگی یا نام نمایشی خالی",
               "high",
               "هر شخص فعال باید نام، نام‌خانوادگی و نام نمایشی معتبر داشته باشد؛ خالی بودن هرکدام، گزارش‌ها و مکاتبات را مخدوش می‌کند.",
               "ثبت سریع بدون اعتبارسنجی، یا پاک‌شدن دستی فیلدها در ویرایش‌های قبلی.",
               "از صفحه اشخاص، اصلاح رکوردهای فهرست‌شده را انجام دهید و فیلدهای خالی را پر کنید.")
    c.set_total(len(active))
    for p in active:
        if not _s(p.given_name) or not _s(p.family_name) or not _s(p.display_name):
            c.hit({"person_id": str(p.id), "display_name": _s(p.display_name) or "—",
                   "given_name": _s(p.given_name) or "—", "family_name": _s(p.family_name) or "—",
                   "version": p.version})
    checks.append(c)

    # ۲) یکتایی نام (نامزد تکرار)
    by_name: dict[str, list[Person]] = {}
    for p in active:
        key = " ".join(_s(f"{p.given_name} {p.family_name}").split()).lower()
        by_name.setdefault(key, []).append(p)
    c = _Check("persons_duplicate_names", "uniqueness", "persons",
               "نام و نام‌خانوادگی یکسان بین چند شخص",
               "high",
               "چند شخص فعال با نام کامل یکسان وجود دارد؛ ممکن است یک نفر چندبار ثبت شده باشد.",
               "ثبت مجدد شخص بدون جست‌وجوی قبلی، یا ورود دسته‌ای منابع مختلف بدون تطابق.",
               "از کارت «جریان رفع تکرار» در همین صفحه پرونده بررسی بسازید و پس از تأیید انسانی، ادغام کنترل‌شده انجام دهید.")
    c.set_total(len(active))
    for key, group in by_name.items():
        if len(group) > 1:
            for p in group:
                c.hit({"person_id": str(p.id), "display_name": p.display_name,
                       "name_key": key, "group_size": len(group), "version": p.version})
    checks.append(c)

    # ۳) یکتایی شناسه تأییدشده
    idents = list(db.execute(select(PersonIdentifier).where(
        PersonIdentifier.tenant_id == tenant_id, PersonIdentifier.status == "active")).scalars().all())
    by_hash: dict[tuple, list[PersonIdentifier]] = {}
    for i in idents:
        if i.verification_status == "verified":
            by_hash.setdefault((i.value_hash, i.type), []).append(i)
    c = _Check("persons_duplicate_verified_identifier", "uniqueness", "persons",
               "شناسه تأییدشده یکسان بین چند شخص",
               "high",
               "یک شناسه تأییدشده (مثل کد ملی) به چند شخص فعال وصل است — قطعاً خطای هویتی است.",
               "ثبت یک شخص با شناسه مشترک/اشتباه، یا عدم ادغام پس از کشف تکرار.",
               "پرونده تکرار بسازید، شخص اصلی را انتخاب و ادغام کنید؛ نگاشت‌ها منتقل و alias حفظ می‌شود.")
    c.set_total(len(idents))
    for (vh, itype), group in by_hash.items():
        if len({str(i.person_id) for i in group}) > 1:
            for i in group:
                p = pid_of.get(str(i.person_id))
                c.hit({"person_id": str(i.person_id), "display_name": p.display_name if p else "—",
                       "identifier_type": i.type, "issuer": i.issuer,
                       "value_masked": i.value_masked})
    checks.append(c)

    # ۴) اعتبار: شناسه‌های تأییدنشده
    c = _Check("persons_unverified_identifiers", "validity", "persons",
               "شناسه‌های فعالِ تأییدنشده",
               "medium",
               "شناسه فعال اما بدون تأیید؛ تا زمان تأیید، قابل اتکا برای تطابق بین‌سامانه‌ای نیست.",
               "ورود شناسه از منابع غیررسمی یا عدم پیگیری فرآیند تأیید.",
               "مقیاس را از منبع رسمی استعلام و تأیید کنید، یا شناسه را لغو کنید.")
    c.set_total(len(idents))
    for i in idents:
        if i.verification_status == "unverified":
            p = pid_of.get(str(i.person_id))
            c.hit({"person_id": str(i.person_id), "display_name": p.display_name if p else "—",
                   "identifier_type": i.type, "issuer": i.issuer, "value_masked": i.value_masked})
    checks.append(c)

    # ۵) پوشش: شخص بدون هیچ شناسه فعال
    have_id: set[str] = {str(i.person_id) for i in idents}
    c = _Check("persons_without_identifier", "coverage", "persons",
               "شخص فعال بدون شناسه",
               "low",
               "شخصی که هیچ شناسه فعالی ندارد؛ در تطابق بین‌سامانه‌ها و کشف تکرار شرکت داده نمی‌شود.",
               "ثبت حداقلی هنگام ورود اولیه.",
               "حداقل یک شناسه (مثل کد ملی یا شماره دانشجویی) ثبت و در نوبت تأیید قرار دهید.")
    c.set_total(len(active))
    for p in active:
        if str(p.id) not in have_id:
            c.hit({"person_id": str(p.id), "display_name": p.display_name, "version": p.version})
    checks.append(c)

    # ۶) انسجام: نگاشت فعالِ متصل به شخص ادغام‌شده
    merged_ids = {str(p.id) for p in merged}
    maps_person = list(db.execute(select(ExternalIdMapping).where(
        ExternalIdMapping.tenant_id == tenant_id,
        ExternalIdMapping.entity_type == "person")).scalars().all())
    c = _Check("persons_merged_with_active_mapping", "integrity", "persons",
               "نگاشت فعالِ متصل به شخص ادغام‌شده",
               "high",
               "نگاشت زیرسامانه به شناسه‌ای اشاره می‌کند که ادغام شده و دیگر مرجع نیست؛ داده زیرسامانه به شناسه مرده می‌رسد.",
               "ادغام پیش از انتقال نگاشت‌ها بازگردانی شده، یا نگاشت بعداً دوباره به شناسه قدیم داده شده است.",
               "نگاشت را به شناسه نهایی ادغام (merged_into_id) به‌روزرسانی کنید؛ فهرست ردیف‌ها همین کار را نشان می‌دهد.")
    c.set_total(len(maps_person))
    for m in maps_person:
        if str(m.entity_id) in merged_ids:
            p = pid_of.get(str(m.entity_id))
            c.hit({"mapping_id": str(m.id), "local_id": m.local_id,
                   "installation_id": str(m.installation_id),
                   "merged_person_id": str(m.entity_id),
                   "display_name": p.display_name if p else "—"})
    checks.append(c)


def _run_org_checks(db: Session, tenant_id, checks: list[_Check]) -> None:
    orgs = list(db.execute(select(Organization).where(
        Organization.tenant_id == tenant_id)).scalars().all())
    by_id = {str(o.id): o for o in orgs}

    # ۷) یکتایی (نوع، کد)
    by_key: dict[tuple, list[Organization]] = {}
    for o in orgs:
        by_key.setdefault((o.type, _s(o.code)), []).append(o)
    c = _Check("orgs_duplicate_code", "uniqueness", "organizations",
               "کد سازمانی تکراری در یک نوع واحد",
               "high",
               "دو واحد سازمانی از یک نوع، کد یکسان دارند؛ سامانه‌های دیگر با کد به همین رکورد وصل می‌شوند و دو مرجع یعنی رفتار نامشخص.",
               "ثبت دستی بدون کنترل یکتایی، یا تغییر کد بدون بررسی (در نسخه‌های قبل کنترل در PATCH وجود نداشت).",
               "کد یکی از ردیف‌ها را به مقدار یکتا اصلاح کنید — از همین صفحه، دکمه اصلاح، فیلد کد.")
    c.set_total(len(orgs))
    for key, group in by_key.items():
        if _s(key[1]) and len(group) > 1:
            for o in group:
                c.hit({"org_id": str(o.id), "type": o.type, "code": o.code,
                       "name": o.name, "version": o.version})
    checks.append(c)

    # ۸) کامل‌بودن نام/کد
    c = _Check("orgs_missing_name_or_code", "completeness", "organizations",
               "واحد سازمانی بدون نام یا کد",
               "medium",
               "نام یا کد خالی، نمایش درخت و ارجاع از زیرسامانه‌ها را می‌شکند.",
               "ثبت سریع ساختار یا پاک‌شدن دستی فیلد.",
               "از دکمه اصلاح، نام/کد را کامل کنید.")
    c.set_total(len(orgs))
    for o in orgs:
        if not _s(o.name) or not _s(o.code):
            c.hit({"org_id": str(o.id), "type": o.type, "code": _s(o.code) or "—",
                   "name": _s(o.name) or "—"})
    checks.append(c)

    # ۹) مرجعیت: والد ناموجود
    c = _Check("orgs_orphan_parent", "integrity", "organizations",
               "واحد با والد ناموجود",
               "high",
               "parent_id به رکوردی اشاره می‌کند که در این مشتری وجود ندارد؛ شاخه در درخت نمایش داده نمی‌شود.",
               "حذف/انتقال والد در نسخه‌های قبلی یا خطای ورود دسته‌ای.",
               "والد معتبر را از مودال اصلاح انتخاب کنید یا واحد را به ریشه منتقل کنید.")
    c.set_total(len(orgs))
    for o in orgs:
        if o.parent_id is not None and str(o.parent_id) not in by_id:
            c.hit({"org_id": str(o.id), "name": o.name, "code": o.code,
                   "missing_parent_id": str(o.parent_id)})
    checks.append(c)

    # ۱۰) انسجام: چرخه در ساختار
    c = _Check("orgs_cycle", "integrity", "organizations",
               "چرخه در ساختار سازمانی",
               "high",
               "زنجیره والد-فرزند به خودش برمی‌گردد؛ پیمایش درخت بی‌نهایت می‌شود و واحد از ریشه جدا می‌افتد.",
               "جابه‌جایی دستی والد بدون کنترل چرخه در داده‌های وارد‌شده از بیرون.",
               "والد یکی از گره‌های حلقه را به ریشه (بدون والد) تغییر دهید تا حلقه باز شود.")
    c.set_total(len(orgs))
    for o in orgs:
        seen: set[str] = set()
        cur = o
        while cur is not None and cur.parent_id is not None:
            key = str(cur.id)
            if key in seen:
                c.hit({"org_id": str(o.id), "name": o.name, "code": o.code,
                       "cycle_root": key})
                break
            seen.add(key)
            cur = by_id.get(str(cur.parent_id))
    checks.append(c)


def _run_reference_checks(db: Session, tenant_id, checks: list[_Check]) -> None:
    sets = list(db.execute(select(ReferenceSet).where(
        ReferenceSet.tenant_id == tenant_id)).scalars().all())
    items = list(db.execute(select(ReferenceItem).where(
        ReferenceItem.tenant_id == tenant_id)).scalars().all())
    set_title = {str(s.id): s.title for s in sets}
    set_code = {str(s.id): s.code for s in sets}
    by_id = {str(i.id): i for i in items}

    # ۱۱) یکتایی کد آیتم در هر مجموعه
    by_key: dict[tuple, list[ReferenceItem]] = {}
    for i in items:
        by_key.setdefault((str(i.set_id), _s(i.code)), []).append(i)
    c = _Check("refs_duplicate_item_code", "uniqueness", "references",
               "کد آیتم تکراری در یک مجموعه",
               "high",
               "در یک مجموعه مرجع، دو آیتم فعال کد یکسان دارند؛ ارجاع با کد مبهم می‌شود.",
               "افزودن آیتم تکراری از دو مسیر (ورود دستی + seed) بدون کنترل.",
               "کد یکی را اصلاح یا آیتم اضافی را بازنشسته کنید.")
    c.set_total(len(items))
    for key, group in by_key.items():
        if _s(key[1]) and len(group) > 1:
            for i in group:
                c.hit({"item_id": str(i.id), "set": set_title.get(str(i.set_id), key[0]),
                       "code": i.code, "title": i.title})
    checks.append(c)

    # ۱۲) مرجعیت: والد ناموجود یا خارج از مجموعه
    c = _Check("refs_orphan_parent", "integrity", "references",
               "آیتم با والد ناموجود یا خارج از مجموعه",
               "medium",
               "parent_id آیتم به آیتمی دیگر اشاره می‌کند که وجود ندارد یا در مجموعه دیگری است؛ ساختار درختی می‌شکند.",
               "حذف آیتم والد یا خطای درج گروهی.",
               "والد را اصلاح یا مقدار parent_id را خالی (بی‌والد) کنید.")
    c.set_total(len(items))
    for i in items:
        if i.parent_id is not None:
            parent = by_id.get(str(i.parent_id))
            if parent is None or parent.set_id != i.set_id:
                c.hit({"item_id": str(i.id), "set": set_title.get(str(i.set_id), "—"),
                       "code": i.code, "title": i.title,
                       "parent_ok": parent is not None})
    checks.append(c)

    # ۱۳) انسجام: لینک‌های شکسته پیش‌نیاز در درس‌های یکتا (سرگروه‌های SEC-* درس نیستند)
    uc_items = [i for i in items if set_code.get(str(i.set_id)) == "unique_courses"
                and i.status == "active" and not _s(i.code).startswith("SEC-")]
    course_codes: set[str] = {_s(i.code) for i in uc_items}
    total_links = 0
    c = _Check("refs_broken_prereq_links", "integrity", "references",
               "لینک پیش‌نیازِ به کد ناموجود",
               "medium",
               "در attrs درس‌های یکتا، پیش‌نیازی به کدی اشاره می‌کند که در فهرست درس‌ها نیست — زنجیره پیش‌نیاز ناقص می‌ماند.",
               "تغییر/حذف درسِ پیش‌نیاز در سامانه منبع پس از استخراج، یا پیش‌نیاز خارج از فهرست.",
               "کد پیش‌نیاز را با فهرست درس‌ها تطابق دهید؛ اگر درس واقعاً حذف شده، مدخل را از prerequisite خام بازخوانی کنید.")
    for i in uc_items:
        attrs = i.attrs or {}
        for pre in attrs.get("prerequisites") or []:
            total_links += 1
            if _s(str(pre.get("code", ""))) not in course_codes:
                c.hit({"item_code": i.code, "title": i.title,
                       "prereq_code": pre.get("code"), "prereq_title": pre.get("title")})
    c.set_total(total_links)
    checks.append(c)

    # ۱۴) کامل‌بودن: ظرفیت برآوردی درس‌های یکتا
    c = _Check("refs_missing_estimated_capacity", "completeness", "references",
               "درس بدون ظرفیت برآوردی",
               "low",
               "فیلد ظرفیت برآوردی در منبع عمومی 8082 وجود ندارد و عمداً خالی گذاشته شده؛ تا زمان ثبت، برنامه‌ریزی ظرفیت قابل انجام نیست.",
               "داده منبع (endpoint عمومی) این فیلد را منتشر نمی‌کند.",
               "از صفحه اطلاعات پایه، در مجموعه «درس‌های یکتا» با دکمه اصلاح، ظرفیت هر درس را ثبت کنید.")
    c.set_total(len(uc_items))
    for i in uc_items:
        cap = (i.attrs or {}).get("estimated_capacity")
        if cap is None or cap == "":
            c.hit({"item_code": i.code, "title": i.title, "estimated_capacity": "—"})
    checks.append(c)

    # ۱۵) به‌روزبودن: آیتم منقضی که هنوز فعال است
    today = utcnow().date()
    dated = [i for i in items if i.valid_to]
    c = _Check("refs_expired_still_active", "freshness", "references",
               "آیتم منقضی که هنوز فعال است",
               "medium",
               "valid_to گذشته اما وضعیت هنوز active است؛ مصرف‌کننده‌ها مقدار منقضی را به‌عنوان معتبر می‌خوانند.",
               "عدم اجرای چرخه بازنشستگی در سررسید.",
               "وضعیت آیتم را به retired تغییر دهید یا valid_to را تمدید کنید.")
    c.set_total(len(dated))
    for i in dated:
        try:
            exp = datetime.strptime(str(i.valid_to)[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if exp < today and i.status == "active":
            c.hit({"item_id": str(i.id), "set": set_title.get(str(i.set_id), "—"),
                   "code": i.code, "title": i.title, "valid_to": str(i.valid_to)[:10]})
    checks.append(c)


def _run_mapping_checks(db: Session, tenant_id, checks: list[_Check]) -> None:
    maps = list(db.execute(select(ExternalIdMapping).where(
        ExternalIdMapping.tenant_id == tenant_id)).scalars().all())
    installations = list(db.execute(select(SystemInstallation).where(
        SystemInstallation.tenant_id == tenant_id)).scalars().all())
    inst_by_id = {str(x.id): x for x in installations}
    persons = list(db.execute(select(Person).where(Person.tenant_id == tenant_id)).scalars().all())
    orgs = list(db.execute(select(Organization).where(
        Organization.tenant_id == tenant_id)).scalars().all())
    person_status = {str(p.id): p.status for p in persons}
    org_ids = {str(o.id) for o in orgs}

    # ۱۶) مرجعیت: نگاشت به موجودیت ناموجود یا ادغام‌شده
    c = _Check("mappings_dangling_entity", "integrity", "mappings",
               "نگاشت به موجودیت ناموجود یا ادغام‌شده",
               "high",
               "نگاشت شناسه محلی زیرسامانه به شناسه مشترکی اشاره می‌کند که وجود ندارد (یا ادغام شده)؛ همگام‌سازی زیرسامانه شکست می‌خورد.",
               "حذف سخت رکورد هدف، یا نگاشت قدیمی متصل به شناسه ادغام‌شده.",
               "نگاشت را به شناسه مرجع فعلی بازنویسی یا حذف کنید؛ ستون وضعیت هدف ریشه را نشان می‌دهد.")
    c.set_total(len(maps))
    for m in maps:
        target_status = None
        if m.entity_type == "person":
            target_status = person_status.get(str(m.entity_id))
            bad = target_status is None or target_status == statuses.PERSON_MERGED
        elif m.entity_type == "organization":
            bad = str(m.entity_id) not in org_ids
        else:
            continue
        if bad:
            inst = inst_by_id.get(str(m.installation_id))
            c.hit({"mapping_id": str(m.id), "local_id": m.local_id,
                   "entity_type": m.entity_type, "entity_id": str(m.entity_id),
                   "entity_status": target_status or "missing",
                   "installation": inst.title if inst else str(m.installation_id)})
    checks.append(c)

    # ۱۷) پوشش/پیکربندی: نگاشت به نصبِ غیرفعال یا حالت مستقل
    c = _Check("mappings_inactive_installation", "coverage", "mappings",
               "نگاشت متصل به نصبِ غیرفعال یا مستقل",
               "low",
               "زیرسامانه مبدأ نگاشت، غیرفعال یا در حالت local است؛ نگاشت عملاً بلااستفاده است و آمار یکپارچگی را مخدوش می‌کند.",
               "خروج زیرسامانه از اکوسیستم بدون پاک‌سازی نگاشت‌ها.",
               "پس از بررسی، نگاشت‌های بلااستفاده را آرشیو/حذف یا نصب را دوباره فعال کنید.")
    c.set_total(len(maps))
    for m in maps:
        inst = inst_by_id.get(str(m.installation_id))
        if inst is None or inst.status != "active" or inst.mode == "local":
            c.hit({"mapping_id": str(m.id), "local_id": m.local_id,
                   "entity_type": m.entity_type,
                   "installation": inst.title if inst else "ناموجود",
                   "installation_status": inst.status if inst else "missing",
                   "mode": inst.mode if inst else "—"})
    checks.append(c)


def _run_syllabus_checks(db: Session, tenant_id, checks: list[_Check]) -> None:
    """بررسی‌های کیفیت سرفصل‌های مصوب — حوزه syllabi (کامل‌بودن، یکتایی، پوشش)."""
    rows = list(db.execute(select(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant_id,
        CourseSyllabus.status == "active")).scalars().all())
    if not rows:
        return
    tcount = dict(db.execute(
        select(CourseSyllabusTopic.syllabus_id, func.count()).group_by(
            CourseSyllabusTopic.syllabus_id)).all())

    def _row(s: CourseSyllabus) -> dict:
        return {"syllabus_id": str(s.id), "title_fa": s.title_fa or "—",
                "title_en": s.title_en, "source_set": s.source_set,
                "topics_count": tcount.get(s.id, 0)}

    # ۱۸) پوشش: سند اسکن‌شده بدون لایه متنی — جزئیات هنوز OCR نشده
    c = _Check("syllabi_scanned_no_text", "coverage", "syllabi",
               "سند سرفصل اسکن‌شده بدون متن استخراج‌شده",
               "medium",
               "PDF منبع اسکن‌شده است و جزئیات (هدف، سرفصل‌ها، منابع) هنوز ثبت نشده؛ فقط کاتالوگ اولیه (عنوان) موجود است.",
               "سند اصلی ویندوز/موبایل اسکن‌شده با کیفیت پایین؛ OCR فارسی انجام نشده.",
               "سند را با OCR فارسی بازخوانی و با ایمپورت همان source_file بروزرسانی کنید.")
    c.set_total(len(rows))
    for s in rows:
        if not s.has_text:
            c.hit(_row(s))
    checks.append(c)

    # ۱۹) کامل‌بودن: عنوان فارسی خالی
    c = _Check("syllabi_missing_title_fa", "completeness", "syllabi",
               "عنوان فارسی درس ثبت نشده",
               "medium",
               "بدون عنوان فارسی، تطبیق سرفصل با درس‌های یکتا و جست‌وجوی کاربران فارسی‌زبان ناقص می‌ماند.",
               "استخراج خودکار عنوان فارسی از سند ممکن است شکست خورده باشد.",
               "عنوان فارسی را از سند منبع استخراج و با ایمپورت idempotent بروزرسانی کنید.")
    c.set_total(len(rows))
    for s in rows:
        if not _s(s.title_fa):
            c.hit(_row(s))
    checks.append(c)

    # ۲۰) کامل‌بودن: کد درس خالی
    c = _Check("syllabi_missing_course_code", "completeness", "syllabi",
               "کد درس ثبت نشده",
               "low",
               "کد درس پیوند سرفصل با سیستم‌های برنامه‌ریزی/تربیت است؛ نبودش تطبیق خودکار را از کار می‌اندازد.",
               "قالب سند منبع کد درس نداشته یا استخراج نشده.",
               "کد رسمی درس را ثبت کنید؛ در نبود کد، تطبیق بر اساس عنوان انجام می‌شود.")
    c.set_total(len(rows))
    for s in rows:
        if not _s(s.course_code):
            c.hit(_row(s))
    checks.append(c)

    # ۲۱) کامل‌بودن: واحد و ساعت نامشخص
    c = _Check("syllabi_missing_units_hours", "completeness", "syllabi",
               "واحد یا ساعت درس نامشخص",
               "medium",
               "هیچ مقداری برای واحد/ساعت (نظری یا عملی) ثبت نشده؛ برنامه‌ریزی درسی نمی‌تواند از این سرفصل استفاده کند.",
               "سند منبع فیلد واحد/ساعت نداشته یا اسکن‌شده است.",
               "واحد و ساعت نظری/عملی را از سند مصوب استخراج و بروزرسانی کنید.")
    c.set_total(len(rows))
    for s in rows:
        if s.unit_theory is None and s.unit_practice is None and \
           s.hour_theory is None and s.hour_practice is None:
            c.hit(_row(s))
    checks.append(c)

    # ۲۲) کامل‌بودن: بدون سرفصل/ریز محتوا
    c = _Check("syllabi_no_topics", "completeness", "syllabi",
               "درس بدون هیچ سرفصل/ریز محتوایی",
               "high",
               "قلب داده سرفصل‌ها خالی است؛ سایر سامانه‌ها (برنامه‌ریزی، سنجش، آموزش) محتوای قابل مصرفی ندارند.",
               "سند اسکن‌شده بدون OCR، یا بخش فهرست مطالب در سند منبع نیامده.",
               "فهرست مطالب سند را استخراج و با ایمپورت همان source_file اضافه کنید.")
    c.set_total(len(rows))
    for s in rows:
        if tcount.get(s.id, 0) == 0:
            c.hit(_row(s))
    checks.append(c)

    # ۲۳) کامل‌بودن: بدون هدف کلی
    c = _Check("syllabi_missing_goal", "completeness", "syllabi",
               "هدف کلی درس ثبت نشده",
               "low",
               "هدف کلی، خلاصه راهبردی سند است؛ نبودش کیفیت نمایش سرفصل در سامانه‌های مصرف‌کننده را می‌کاهد.",
               "بخش اهداف در سند منبع نبوده یا استخراج نشده.",
               "هدف کلی را از سند منبع تکمیل کنید.")
    c.set_total(len(rows))
    for s in rows:
        if not _s(s.general_goal):
            c.hit(_row(s))
    checks.append(c)

    # ۲۴) یکتایی: عنوان تکراری در یک مجموعه
    by_key: dict[tuple, list] = {}
    for s in rows:
        key_title = _s(s.title_fa) or _s(s.title_en)
        key_title = " ".join(key_title.split()).lower()
        if key_title:
            by_key.setdefault((s.source_set, key_title), []).append(s)
    c = _Check("syllabi_duplicate_title_in_set", "uniqueness", "syllabi",
               "عنوان تکراری در یک مجموعه",
               "medium",
               "دو سند با عنوان یکسان در یک مجموعه مصوب ثبت شده؛ احتمال تکرار فایل یا خطای پارس.",
               "فایل تکراری در منبع، یا عنوان پیش‌فرض یکسان از نام‌گذاری اشتباه.",
               "سند تکراری را پس از بررسی حذف یا عنوان را اصلاح کنید؛ ردیف‌های زیر فهرست تکراری‌هاست.")
    c.set_total(len(rows))
    for (sset, _title), group in sorted(by_key.items()):
        if len(group) > 1:
            for s in group:
                row = _row(s)
                row["duplicate_in"] = sset
                c.hit(row)
    checks.append(c)

    # ۲۵) یکتایی: کد درس تکراری در یک مجموعه
    by_code: dict[tuple, list] = {}
    for s in rows:
        code = _s(s.course_code)
        if code:
            by_code.setdefault((s.source_set, code), []).append(s)
    c = _Check("syllabi_duplicate_code_in_set", "uniqueness", "syllabi",
               "کد درس تکراری در یک مجموعه",
               "low",
               "یک کد به دو سند مختلف اختصاص یافته؛ پیوند خودکار با درس‌های یکتا مبهم می‌شود.",
               "خطای پارس استخراج کد، یا دو نسخه از یک درس با کد مشترک.",
               "کد را برای هر سند یکتا کنید یا یکی از رکوردها را حذف نمایید.")
    c.set_total(len(rows))
    for (sset, _code), group in sorted(by_code.items()):
        if len(group) > 1:
            for s in group:
                row = _row(s)
                row["duplicate_code_in"] = sset
                c.hit(row)
    checks.append(c)


def run_overview(db: Session, tenant_id) -> dict:
    """داشبورد تجمیعی کیفیت: امتیاز کل، ابعاد، حوزه‌ها و بررسی‌ها با ردیف‌های drill-down."""
    checks: list[_Check] = []
    _run_person_checks(db, tenant_id, checks)
    _run_org_checks(db, tenant_id, checks)
    _run_reference_checks(db, tenant_id, checks)
    _run_mapping_checks(db, tenant_id, checks)
    _run_syllabus_checks(db, tenant_id, checks)

    outs = [c.out() for c in checks]
    wsum = sum(WEIGHTS[c["severity"]] for c in outs)
    score = round(100 * sum(WEIGHTS[c["severity"]] * c["pass_rate"] / 100 for c in outs) / wsum) if wsum else 100

    dimensions = []
    for key, title in DIMENSIONS:
        group = [c for c in outs if c["dimension"] == key]
        if not group:
            continue
        g_wsum = sum(WEIGHTS[c["severity"]] for c in group)
        g_score = round(100 * sum(WEIGHTS[c["severity"]] * c["pass_rate"] / 100 for c in group) / g_wsum) if g_wsum else 100
        dimensions.append({"key": key, "title": title, "score": g_score,
                           "checks": len(group),
                           "affected": sum(c["affected"] for c in group)})

    domains = []
    for key, title in DOMAINS:
        group = [c for c in outs if c["domain"] == key]
        if not group:
            continue
        g_wsum = sum(WEIGHTS[c["severity"]] for c in group)
        g_score = round(100 * sum(WEIGHTS[c["severity"]] * c["pass_rate"] / 100 for c in group) / g_wsum) if g_wsum else 100
        domains.append({"key": key, "title": title, "score": g_score,
                        "checks": len(group),
                        "affected": sum(c["affected"] for c in group)})

    from app.modules.data_quality.models import MergeRecord, ResolutionCase
    open_cases = len(list(db.execute(select(ResolutionCase.id).where(
        ResolutionCase.tenant_id == tenant_id, ResolutionCase.status == "open")).all()))
    decided_cases = len(list(db.execute(select(ResolutionCase.id).where(
        ResolutionCase.tenant_id == tenant_id, ResolutionCase.status == "decided")).all()))
    merges_applied = len(list(db.execute(select(MergeRecord.id).where(
        MergeRecord.tenant_id == tenant_id, MergeRecord.status == "applied")).all()))
    merges_reversed = len(list(db.execute(select(MergeRecord.id).where(
        MergeRecord.tenant_id == tenant_id, MergeRecord.status == "reversed")).all()))

    return {
        "score": score,
        "counts": {
            "checks": len(outs),
            "ok": sum(1 for c in outs if c["status"] == "ok"),
            "warn": sum(1 for c in outs if c["status"] == "warn"),
            "fail": sum(1 for c in outs if c["status"] == "fail"),
            "affected": sum(c["affected"] for c in outs),
        },
        "dimensions": dimensions,
        "domains": domains,
        "checks": outs,
        "ops": {"open_cases": open_cases, "decided_cases": decided_cases,
                "merges_applied": merges_applied, "merges_reversed": merges_reversed},
    }
