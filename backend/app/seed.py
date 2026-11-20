"""داده نمونه دمو — idempotent؛ فقط برای توسعه/پایلوت.

در تولید، داده واقعی از مهاجرت/تطبیق نصب‌های مستقل وارد می‌شود، نه از این فایل.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import Actor
from app.modules.identities.service import register_mapping
from app.modules.integrations.models import SystemInstallation, Tenant
from app.modules.integrations.service import create_installation, create_tenant
from app.modules.persons.models import PersonIdentifier
from app.modules.persons.service import add_contact, add_identifier, create_person
from app.modules.references.service import create_item, create_set

log = logging.getLogger("core.seed")

DEMO_TENANT_CODE = "demo"

_REF_SETS = {
    "gender": ("جنسیت", [("male", "مرد"), ("female", "زن")]),
    "org_types": ("انواع واحد سازمانی", [
        ("university", "دانشگاه"), ("campus", "پردیس"), ("faculty", "دانشکده"),
        ("department", "گروه آموزشی"), ("unit", "واحد اداری"),
    ]),
    "identifier_types": ("انواع شناسه", [
        ("national_id", "کد ملی"), ("student_number", "شماره دانشجویی"),
        ("personnel_number", "شماره پرسنلی"), ("passport", "شماره گذرنامه"),
    ]),
    "contact_types": ("انواع تماس", [
        ("email", "ایمیل"), ("mobile", "تلفن همراه"), ("phone", "تلفن ثابت"),
    ]),
    "degree_levels": ("مقاطع تحصیلی", [
        ("associate", "کاردانی"), ("bachelor", "کارشناسی"), ("master", "کارشناسی ارشد"),
        ("phd", "دکتری تخصصی"),
    ]),
    "semester_terms": ("نیمسال‌ها", [
        ("1403-1", "نیمسال اول ۱۴۰۳-۱۴۰۴"), ("1403-2", "نیمسال دوم ۱۴۰۳-۱۴۰۴"),
        ("1404-1", "نیمسال اول ۱۴۰۴-۱۴۰۵"),
    ]),
    "person_statuses": ("وضعیت شخص در هسته", [
        ("active", "فعال"), ("inactive", "غیرفعال"), ("merged", "ادغام‌شده"),
    ]),
}

DEMO_ORGS = [
    # (type, code, name, parent_code)
    ("university", "U100", "دانشگاه نمونه", None),
    ("faculty", "F10", "دانشکده فنی و مهندسی", "U100"),
    ("faculty", "F20", "دانشکده علوم پایه", "U100"),
    ("department", "D101", "گروه مهندسی کامپیوتر", "F10"),
    ("department", "D102", "گروه مهندسی برق", "F10"),
    ("department", "D201", "گروه ریاضی", "F20"),
]

DEMO_PERSONS = [
    # (نام, نام خانوادگی, شناسه‌ها[(type, issuer, value, verified)], تماس‌ها[(type, value)])
    ("علی", "رضایی", [("national_id", "civil_registry", "0012345678", "unverified"),
                      ("student_number", "edu", "402113001", "verified")],
     [("email", "ali.rezaei@example.ac.ir"), ("mobile", "09121110001")]),
    ("سارا", "محمدی", [("national_id", "civil_registry", "0023456789", "verified"),
                       ("student_number", "edu", "402113002", "verified")],
     [("email", "sara.mohammadi@example.ac.ir"), ("mobile", "09121110002")]),
    ("محمدکریم", "احمدی", [("national_id", "civil_registry", "0034567890", "unverified")],
     [("email", "m.ahmadi@example.ac.ir")]),
    ("فاطمه", "حسینی", [("national_id", "civil_registry", "0045678901", "verified")],
     [("email", "f.hosseini@example.ac.ir"), ("phone", "02188776655")]),
    ("علی", "رضایی", [("student_number", "edu", "401199007", "unverified")],
     [("email", "a.rezaei2@example.ac.ir")]),
    ("رضا", "کریمی", [], [("email", "r.karimi@example.ac.ir")]),
    ("مینا", "قاسمی", [("personnel_number", "hr", "10245", "unverified")], []),
]


def seed_demo(db: Session) -> None:
    existing = db.execute(select(Tenant).where(Tenant.code == DEMO_TENANT_CODE)).scalar_one_or_none()
    if existing is not None:
        return
    log.info("Seeding demo tenant ...")
    actor = Actor(kind="user", subject="seed", name="Seed", roles={"tenant_admin", "steward"},
                  tenant_codes=[DEMO_TENANT_CODE], issuer="dev")

    tenant = create_tenant(db, actor, {
        "code": DEMO_TENANT_CODE, "name": "دانشگاه نمونه (دمو)",
        "note": "مشتری نمونه برای توسعه و پایلوت",
    })
    edu = create_installation(db, tenant.id, actor, {
        "system_code": "edu", "installation_code": "edu-main", "title": "سامانه آموزشی",
        "mode": "integrated", "base_url": "http://edu.example.local",
        "owner_scopes": "owner:person,read:person,sync",
    })
    create_installation(db, tenant.id, actor, {
        "system_code": "research", "installation_code": "research-main", "title": "سامانه پژوهش",
        "mode": "local", "base_url": "http://research.example.local", "owner_scopes": "read:person,sync",
    })
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
        create_set(db, tenant.id, actor, {"code": code, "title": title, "description": "فهرست مرجع نمونه"})
        for sort, (item_code, item_title) in enumerate(items):
            create_item(db, tenant.id, actor, code, {
                "code": item_code, "title": item_title, "sort_order": sort,
            })

    for given, family, idents, contacts in DEMO_PERSONS:
        person = create_person(db, tenant.id, actor, {"given_name": given, "family_name": family})
        for itype, issuer, value, verified in idents:
            add_identifier(db, tenant.id, actor, person["id"], {
                "type": itype, "issuer": issuer, "value": value, "verification_status": verified,
            })
            if itype == "student_number":
                # نگاشت نمونه: شناسه محلی سامانه آموزشی → شناسه مشترک
                try:
                    register_mapping(db, tenant.id, actor, {
                        "installation_id": str(edu.id), "entity_type": "person",
                        "local_id": value, "entity_id": person["id"],
                        "note": "نگاشت نمونه دمو",
                    })
                except Exception as exc:  # noqa: BLE001
                    log.warning("demo mapping skipped: %s", exc)
        for ctype, value in contacts:
            add_contact(db, tenant.id, actor, person["id"], {"type": ctype, "value": value})

    db.commit()
    log.info("Demo seed done (tenant=%s)", tenant.code)
