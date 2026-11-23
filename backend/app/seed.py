"""داده نمونه دمو — idempotent؛ فقط برای توسعه/پایلوت.

مطابق اکوسیستم واقعی دانشجو۳۶۰ روی 188.212.96.235:
- ۹ سامانه متصل (پورت‌های واقعی) + پرتال ورود یکپارچه (SSO/OIDC)
- نیمسال‌های دوره از سامانه برنامه‌ریزی۳۶۰ (مهر/بهمن/تابستان)
- مقاطع، رشته‌ها، انواع اشتغال و دوره‌های روز متناسب با اطلاعات پایه سایر سامانه‌ها

در تولید، داده واقعی از مهاجرت/تطبیق نصب‌های مستقل وارد می‌شود، نه از این فایل.
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import Actor
from app.modules.identities.service import register_mapping
from app.modules.integrations.models import Tenant
from app.modules.integrations.service import create_installation, create_tenant
from app.modules.masterdata.models import CourseSyllabus
from app.modules.masterdata import service as md_service
from app.modules.persons.models import PersonIdentifier
from app.modules.persons.service import add_contact, add_identifier, create_person
from app.modules.references.service import create_item, create_set
from app.seed_courses import COURSE_SECTIONS, UNIQUE_COURSES

log = logging.getLogger("core.seed")

DEMO_TENANT_CODE = "demo"
SSO_BASE = "http://188.212.96.235"

# سامانه‌های اکوسیستم — پورت‌ها و نقش‌های واقعی (پروب 188.212.96.235)
ECOSYSTEM_INSTALLATIONS = [
    # (system_code, installation_code, title, port, mode, owner_scopes)
    ("sso_portal", "sso-portal-8086", "پرتال ورود یکپارچه دانشجویار۳۶۰", 8086,
     "integrated", "read:person,sync"),
    ("survey", "survey-8082", "سامانه نظرسنجی دروس", 8082,
     "integrated", "read:person,sync"),
    ("barnamehyar", "barnamehyar-8083", "سامانه هوشمند برنامه‌ریزی درسی", 8083,
     "integrated", "owner:person,read:person,sync"),
    ("modiriyar", "modiriyar-8087", "مدیریار۳۶۰ — مدیریت آموزشی دانشگاه", 8087,
     "integrated", "read:person,sync"),
    ("pajooheshyar", "pajooheshyar-8088", "پژوهشیار۳۶۰ — پژوهش و مقالات", 8088,
     "integrated", "read:person,sync"),
    ("bashgah", "bashgah-8089", "باشگاه دانشجو۳۶۰", 8089,
     "integrated", "read:person,sync"),
    ("maharatyar", "maharatyar-8090", "مهارت‌یار۳۶۰ — مسیر شغلی و بازار کار", 8090,
     "integrated", "read:person,sync"),
    ("amoozeshyar", "amoozeshyar-8091", "آموزش‌یار۳۶۰ — دستیار آموزش و آیین‌نامه", 8091,
     "integrated", "owner:person,read:person,sync"),
    ("payehyar", "payehyar-8094", "پایه‌یار۳۶۰ — هسته مشترک و اطلاعات پایه (خود سامانه)", 8094,
     "integrated", "owner:person,read:person,sync"),
]

_REF_SETS = {
    "gender": ("جنسیت", [
        ("male", "مرد"), ("female", "زن"),
    ]),
    "org_types": ("انواع واحد سازمانی", [
        ("university", "دانشگاه"), ("campus", "پردیس"), ("faculty", "دانشکده"),
        ("department", "گروه آموزشی"), ("deputy", "معاونت"), ("center", "مرکز"),
        ("office", "دفتر"), ("unit", "واحد اداری"),
    ]),
    "identifier_types": ("انواع شناسه", [
        ("national_id", "کد ملی"), ("student_number", "شماره دانشجویی"),
        ("personnel_number", "شماره پرسنلی"), ("professor_code", "کد استادی"),
        ("passport", "شماره گذرنامه"), ("sso_subject", "شناسه یکپارچه SSO"),
    ]),
    "contact_types": ("انواع تماس", [
        ("email", "ایمیل"), ("mobile", "تلفن همراه"), ("phone", "تلفن ثابت"),
        ("telegram", "تلگرام"), ("internal_phone", "داخلی سازمانی"),
    ]),
    "degree_levels": ("مقاطع تحصیلی", [
        ("associate", "کاردانی"), ("bachelor", "کارشناسی"),
        ("master", "کارشناسی ارشد"), ("phd", "دکتری تخصصی"), ("postdoc", "فوق دکتری"),
    ]),
    # نیمسال‌های دوره — مطابق سامانه برنامه‌ریزی۳۶۰ (8083): مهر / بهمن / تابستان
    "term_periods": ("نیمسال‌های دوره", [
        ("semester_1", "نیمسال اول (مهر)"),
        ("semester_2", "نیمسال دوم (بهمن)"),
        ("summer", "نیمسال تابستان"),
    ]),
    # سال‌های تحصیلی — نظرسنجی دروس (8082) در بهمن ۱۴۰۵ فعال است
    "semester_terms": ("سال‌های تحصیلی", [
        ("1403-1", "سال تحصیلی ۱۴۰۳-۱۴۰۴"), ("1403-2", "سال تحصیلی ۱۴۰۳-۱۴۰۴ (دوم)"),
        ("1404-1", "سال تحصیلی ۱۴۰۴-۱۴۰۵"), ("1404-2", "سال تحصیلی ۱۴۰۴-۱۴۰۵ (دوم)"),
        ("1405-1", "سال تحصیلی ۱۴۰۵-۱۴۰۶"), ("1405-2", "سال تحصیلی ۱۴۰۵-۱۴۰۶ (دوم — جاری)"),
    ]),
    # رشته‌های تحصیلی — متناسب با گروه‌های آموزشی سازمان
    "majors": ("رشته‌های تحصیلی", [
        ("computer_eng", "مهندسی کامپیوتر"), ("it_eng", "مهندسی فناوری اطلاعات"),
        ("electrical_eng", "مهندسی برق"), ("mechanical_eng", "مهندسی مکانیک"),
        ("civil_eng", "مهندسی عمران"), ("architecture", "معماری"),
        ("mathematics", "ریاضی"), ("physics", "فیزیک"),
        ("management", "مدیریت"), ("economics", "اقتصاد"),
    ]),
    # انواع اشتغال — متناسب با اطلاعات پایه پرسنلی
    "employment_types": ("انواع اشتغال", [
        ("faculty", "هیئت علمی"), ("staff", "کارمند"), ("student", "دانشجو"),
        ("contractor", "پیمانی"), ("guest", "مهمان/همکار خارجی"),
    ]),
    # دوره‌های روز — مطابق برنامه‌ریزی۳۶۰ (8083)
    "class_periods": ("دوره‌های روز", [
        ("morning", "صبح"), ("afternoon", "بعدازظهر"), ("evening", "عصر"),
    ]),
    # نقش‌های سامانه‌ای اکوسیستم — برای نگاشت SSO (قرارداد <appKey>.access)
    "system_roles": ("نقش‌های سامانه‌ای اکوسیستم", [
        ("student", "دانشجو"), ("professor", "استاد"), ("advisor", "مشاور"),
        ("dept_manager", "مدیرگروه"), ("edu_manager", "مدیرآموزش"),
        ("sysadmin", "ادمین سیستم"), ("viewer", "مشاهده‌گر"),
        ("hr_access", "دسترسی پایه‌یار (hr.access)"),
    ]),
    "person_statuses": ("وضعیت شخص در هسته", [
        ("active", "فعال"), ("inactive", "غیرفعال"), ("merged", "ادغام‌شده"),
    ]),
}

DEMO_ORGS = [
    # (type, code, name, parent_code)
    ("university", "U100", "دانشگاه نمونه ۳۶۰", None),
    ("deputy", "P1", "معاونت آموزشی", "U100"),
    ("deputy", "P2", "معاونت پژوهشی و فناوری", "U100"),
    ("center", "C1", "مرکز فناوری اطلاعات و شبکه", "U100"),
    ("faculty", "F10", "دانشکده فنی و مهندسی", "U100"),
    ("faculty", "F20", "دانشکده علوم پایه", "U100"),
    ("faculty", "F30", "دانشکده مدیریت و اقتصاد", "U100"),
    ("faculty", "F40", "دانشکده هنر و معماری", "U100"),
    ("department", "D101", "گروه مهندسی کامپیوتر", "F10"),
    ("department", "D102", "گروه مهندسی برق", "F10"),
    ("department", "D103", "گروه مهندسی مکانیک", "F10"),
    ("department", "D201", "گروه ریاضی", "F20"),
    ("department", "D202", "گروه فیزیک", "F20"),
    ("department", "D301", "گروه مدیریت", "F30"),
    ("department", "D302", "گروه اقتصاد", "F30"),
    ("department", "D401", "گروه معماری", "F40"),
]

DEMO_PERSONS = [
    # (نام, نام خانوادگی, شناسه‌ها[(type, issuer, value, verified)], تماس‌ها[(type, value)])
    ("علی", "رضایی", [("national_id", "civil_registry", "0012345678", "unverified"),
                      ("student_number", "edu", "402113001", "verified")],
     [("email", "ali.rezaei@example.ac.ir"), ("mobile", "09121110001")]),
    ("سارا", "محمدی", [("national_id", "civil_registry", "0023456789", "verified"),
                       ("student_number", "edu", "402113002", "verified"),
                       ("sso_subject", "sso", "daneshjo360-88213", "verified")],
     [("email", "sara.mohammadi@example.ac.ir"), ("mobile", "09121110002")]),
    ("محمدکریم", "احمدی", [("national_id", "civil_registry", "0034567890", "unverified"),
                           ("professor_code", "hr", "P-2041", "unverified")],
     [("email", "m.ahmadi@example.ac.ir"), ("internal_phone", "3312")]),
    ("فاطمه", "حسینی", [("national_id", "civil_registry", "0045678901", "verified"),
                        ("personnel_number", "hr", "10245", "verified")],
     [("email", "f.hosseini@example.ac.ir"), ("phone", "02188776655")]),
    ("علی", "رضایی", [("student_number", "edu", "401199007", "unverified")],
     [("email", "a.rezaei2@example.ac.ir")]),
    ("رضا", "کریمی", [("personnel_number", "hr", "10311", "unverified")],
     [("email", "r.karimi@example.ac.ir")]),
    ("مینا", "قاسمی", [("student_number", "edu", "403114010", "unverified")],
     [("mobile", "09121110003")]),
    ("حسین", "مرادی", [("national_id", "civil_registry", "0056789012", "unverified"),
                       ("professor_code", "hr", "P-1987", "verified")],
     [("email", "h.moradi@example.ac.ir"), ("internal_phone", "3345")]),
]


def _syllabi_seed_items() -> list[dict]:
    """سرفصل‌های مصوب پارس‌شده از فایل‌های پیوست — app/data/syllabi.json (در باینری: _MEIPASS)."""
    candidates = [
        Path(__file__).resolve().parent / "data" / "syllabi.json",
        Path(getattr(sys, "_MEIPASS", ".")) / "app" / "data" / "syllabi.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8")).get("items", [])
            except Exception as exc:  # noqa: BLE001
                log.warning("syllabi seed file unreadable (%s): %s", p, exc)
    return []


def _seed_syllabi(db: Session) -> None:
    """واردکردن idempotent سرفصل‌ها در مشتری demo — حتی برای نصب‌های موجود."""
    tenant = db.execute(select(Tenant).where(Tenant.code == DEMO_TENANT_CODE)).scalar_one_or_none()
    if tenant is None:
        return
    has_any = db.execute(select(func.count()).select_from(CourseSyllabus).where(
        CourseSyllabus.tenant_id == tenant.id)).scalar() or 0
    if has_any:
        return
    items = _syllabi_seed_items()
    if not items:
        log.info("Syllabi seed file not found — پرش (قابل ایمپورت از پنل یا API)")
        return
    actor = Actor(kind="user", subject="seed", name="Seed", roles={"tenant_admin", "steward"},
                  tenant_codes=[DEMO_TENANT_CODE], issuer="dev")
    out = md_service.import_syllabi(db, tenant.id, actor, items, source="syllabi-files")
    db.commit()
    log.info("Syllabi seeded: %s", out)


def seed_demo(db: Session) -> None:
    existing = db.execute(select(Tenant).where(Tenant.code == DEMO_TENANT_CODE)).scalar_one_or_none()
    if existing is not None:
        _seed_syllabi(db)
        return
    log.info("Seeding demo tenant ...")
    actor = Actor(kind="user", subject="seed", name="Seed", roles={"tenant_admin", "steward"},
                  tenant_codes=[DEMO_TENANT_CODE], issuer="dev")

    tenant = create_tenant(db, actor, {
        "code": DEMO_TENANT_CODE, "name": "دانشگاه نمونه ۳۶۰ (دمو)",
        "note": "مشتری نمونه اکوسیستم دانشجو۳۶۰ برای توسعه و پایلوت",
    })

    # نصب‌های سامانه‌های اکوسیستم — پورت‌های واقعی 188.212.96.235
    installs = {}
    for system_code, inst_code, title, port, mode, scopes in ECOSYSTEM_INSTALLATIONS:
        inst = create_installation(db, tenant.id, actor, {
            "system_code": system_code, "installation_code": inst_code, "title": title,
            "mode": mode, "base_url": f"{SSO_BASE}:{port}", "owner_scopes": scopes,
        })
        installs[system_code] = inst
    db.flush()

    org_by_code = {}
    for org_type, code, name, parent_code in DEMO_ORGS:
        from app.modules.organizations.service import create_org
        org = create_org(db, tenant.id, actor, {
            "type": org_type, "code": code, "name": name,
            "parent_id": org_by_code.get(parent_code),
            "sort_order": len(org_by_code),
        })
        org_by_code[code] = org["id"]

    for code, (title, items) in _REF_SETS.items():
        create_set(db, tenant.id, actor, {"code": code, "title": title, "description": "فهرست مرجع اکوسیستم دانشجو۳۶۰"})
        for sort, (item_code, item_title) in enumerate(items):
            create_item(db, tenant.id, actor, code, {
                "code": item_code, "title": item_title, "sort_order": sort,
            })

    # ---- درس‌های یکتا — دیتای واقعی سامانه نظرسنجی دروس ۳۶۰ (پورت 8082، صفحه admin/unique-courses) ----
    create_set(db, tenant.id, actor, {
        "code": "course_sections", "title": "گروه‌های درس",
        "description": "گروه‌های دروس یکتا — منبع: سامانه نظرسنجی دروس ۳۶۰ (8082)",
    })
    for s in COURSE_SECTIONS:
        create_item(db, tenant.id, actor, "course_sections", {
            "code": s["code"], "title": s["title"], "sort_order": s["order"],
            "attrs": {"course_count": s["count"], "order": s["order"]},
        })

    create_set(db, tenant.id, actor, {
        "code": "unique_courses", "title": "درس‌های یکتا",
        "description": "۱۴۳ درس واقعی واردشده از سامانه نظرسنجی دروس ۳۶۰ (8082) — فیلدها: کد یکتا، عنوان، "
                       "گروه، ظرفیت برآوردی (در منبع عمومی نیست؛ از پنل قابل ثبت)، واحد نظری/عملی، وضعیت "
                       "+ سال، پیش‌نیازهای لینک‌شده به کد درس و ردیف گروهی در attrs",
    })
    section_item_ids = {}
    for s in COURSE_SECTIONS:
        sec_item = create_item(db, tenant.id, actor, "unique_courses", {
            "code": f"SEC-{s['code']}", "title": s["title"], "sort_order": s["order"],
        })
        section_item_ids[s["code"]] = sec_item["id"]
    for c in UNIQUE_COURSES:
        attrs = {
            "unique_code": c["unique_code"], "group": c["group"],
            "estimated_capacity": c["estimated_capacity"],
            "credits": c["credits"], "credits_theory": c["credits_theory"],
            "credits_practical": c["credits_practical"],
            "status": c["status"],
            "year": c["year"], "year_raw": c["year_raw"],
            "section": c["section"], "group_order": c["group_order"],
            "prerequisite": c["prerequisite"], "prerequisites": c["prereq_codes"],
            "source": "survey-8082", "source_id": c["id"],
        }
        if c.get("year_note"):
            attrs["year_note"] = c["year_note"]
        if c["prereq_unresolved"]:
            attrs["prerequisite_unresolved"] = c["prereq_unresolved"]
        parent = section_item_ids.get(c["section"])
        create_item(db, tenant.id, actor, "unique_courses", {
            # کد یکتا = شناسه خام منبع (بدون پیشوند) — سامانه‌های دیگر با همین کد کار می‌کنند
            "code": str(c["id"]), "title": c["title"], "sort_order": c["group_order"],
            "parent_id": uuid.UUID(parent) if parent else None, "attrs": attrs,
        })

    edu = installs.get("amoozeshyar") or installs.get("payehyar")
    for given, family, idents, contacts in DEMO_PERSONS:
        person = create_person(db, tenant.id, actor, {"given_name": given, "family_name": family})
        for itype, issuer, value, verified in idents:
            add_identifier(db, tenant.id, actor, person["id"], {
                "type": itype, "issuer": issuer, "value": value, "verification_status": verified,
            })
            if itype == "student_number" and edu is not None:
                # نگاشت نمونه: شناسه محلی آموزش‌یار۳۶۰ → شناسه مشترک هسته
                try:
                    register_mapping(db, tenant.id, actor, {
                        "installation_id": str(edu.id), "entity_type": "person",
                        "local_id": value, "entity_id": person["id"],
                        "note": "نگاشت نمونه دمو (آموزش‌یار۳۶۰)",
                    })
                except Exception as exc:  # noqa: BLE001
                    log.warning("demo mapping skipped: %s", exc)
        for ctype, value in contacts:
            add_contact(db, tenant.id, actor, person["id"], {"type": ctype, "value": value})

    db.commit()
    log.info("Demo seed done (tenant=%s, installations=%d)", tenant.code, len(installs))
    _seed_syllabi(db)
