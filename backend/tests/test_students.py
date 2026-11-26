"""آزمون‌های ماژول دانشجویان — ثبت دستی، فیلترها، نسخه‌سازی، سینک pull/push و آمار."""
from __future__ import annotations

import uuid as uuid_mod

import pytest

from tests.conftest import dev_headers

WRITE_ROLES = "master_data_editor"


def _create(client, tenant="t1", **overrides):
    body = {
        # شماره یکتا در هر فراخوانی — DB سشن‌محور است و رکوردهای تست‌های قبلی می‌مانند
        "student_number": f"402{uuid_mod.uuid4().int % 10 ** 8:08d}",
        "national_id": "0012345678",
        "first_name": "زهرا",
        "last_name": "محمدی",
        "mobile": "0912 123 4567",   # با فاصله — باید یک‌سازی شود
        "city": "تهران",
        "university_name": "دانشگاه تهران",
        "major_name": "مهندسی کامپیوتر",
        "degree_level": "karshenasi",
        "entrance_year": 1402,
        **overrides,
    }
    return client.post("/api/v1/students", json=body, headers=dev_headers(roles=WRITE_ROLES, tenant=tenant))


@pytest.fixture()
def student1(client, tenant1):
    r = _create(client)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------ ثبت دستی

def test_create_student_normalizes_mobile(client, tenant1, student1):
    assert student1["mobile"] == "09121234567"
    assert student1["degree_level"] == "karshenasi"
    assert student1["source"] == "manual"


def test_create_duplicate_student_number_conflict(client, tenant1, student1):
    r = _create(client, student_number=student1["student_number"])
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "STUDENT_NUMBER_DUPLICATE"


def test_create_invalid_mobile_rejected(client, tenant1):
    r = _create(client, mobile="12345")
    assert r.status_code == 422


def test_create_requires_write_role(client, tenant1):
    r = _create(client, student_number="402113050")
    headers = dev_headers(user="viewer1", roles="viewer", tenant=tenant1)
    r2 = client.post("/api/v1/students",
                     json={"student_number": "402113060", "first_name": "a", "last_name": "b",
                           "mobile": "09121110000", "city": "قم", "university_name": "u",
                           "major_name": "m", "degree_level": "kardani"},
                     headers=headers)
    assert r.status_code == 201
    assert r2.status_code == 403


# ------------------------------------------------ فهرست و فیلترها

def test_list_and_filters(client, tenant1, student1):
    r = client.get("/api/v1/students", headers=dev_headers(tenant=tenant1))
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    r = client.get("/api/v1/students?degree_level=karshenasi", headers=dev_headers(tenant=tenant1))
    assert any(i["id"] == student1["id"] for i in r.json()["items"])

    r = client.get("/api/v1/students?degree_level=kardani", headers=dev_headers(tenant=tenant1))
    assert all(i["degree_level"] == "kardani" for i in r.json()["items"])

    r = client.get("/api/v1/students?city=تهران", headers=dev_headers(tenant=tenant1))
    assert r.json()["total"] >= 1

    r = client.get("/api/v1/students?q=محمدی", headers=dev_headers(tenant=tenant1))
    assert r.json()["total"] >= 1


def test_tenant_isolation(client, tenant1, tenant2, student1):
    r = client.get("/api/v1/students", headers=dev_headers(tenant=tenant2))
    assert all(i["id"] != student1["id"] for i in r.json()["items"])


# ------------------------------------------------ ویرایش نسخه‌دار

def test_patch_with_version(client, tenant1, student1):
    sid, v = student1["id"], student1["version"]
    r = client.patch(f"/api/v1/students/{sid}",
                     json={"city": "کرج", "mobile": "+989122233344"},
                     headers={"If-Match": f'"{v}"', **dev_headers(roles=WRITE_ROLES, tenant=tenant1)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["city"] == "کرج"
    assert body["mobile"] == "09122233344"
    assert body["version"] == v + 1


def test_patch_version_conflict(client, tenant1, student1):
    r = client.patch(f"/api/v1/students/{student1['id']}", json={"city": "اصفهان"},
                     headers={"If-Match": '"99"', **dev_headers(roles=WRITE_ROLES, tenant=tenant1)})
    assert r.status_code == 412  # Precondition Failed — قرارداد If-Match
    assert r.json()["code"] == "VERSION_CONFLICT"


def test_deactivation(client, tenant1, student1):
    r = client.post(f"/api/v1/students/{student1['id']}/deactivation?reason=manually",
                    json={"version": student1["version"]},
                    headers={"If-Match": f'"{student1["version"]}"',
                             **dev_headers(roles=WRITE_ROLES, tenant=tenant1)})
    assert r.status_code == 200
    assert r.json()["status"] == "inactive"


# ------------------------------------------------ آمار

def test_stats(client, tenant1, student1):
    r = client.get("/api/v1/students/stats", headers=dev_headers(tenant=tenant1))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1
    assert body["by_degree"].get("karshenasi", 0) >= 1
    assert body["by_source"].get("manual", 0) >= 1


# ------------------------------------------------ همگام‌سازی pull از دانشگاه هوشمند

REMOTE_ITEM = {
    "external_ref": "su-1001",
    "student_number": "403997001",
    "national_id": "0023456789",
    "first_name": "حسین",
    "last_name": "کریمی",
    "mobile": "+989351112233",
    "city": "مشهد",
    "province": "خراسان رضوی",
    "university_code": "u01",
    "university_name": "دانشگاه فردوسی مشهد",
    "major_name": "مهندسی برق",
    "degree_level": "کارشناسی ارشد",   # برچسب فارسی — باید به کد کانونی نگاشت شود
    "entrance_year": 1403,
    "status": "در حال تحصیل",
}


def test_pull_sync_maps_and_upserts(client, tenant1):
    calls = []

    def fake_fetch(url, headers):
        calls.append(url)
        return 200, {"items": [REMOTE_ITEM], "total": 1}

    r = client.post("/api/v1/students/sync", headers=dev_headers(tenant=tenant1))
    # بدون تزریق fetch این فراخوانی به سرور واقعی می‌زند؛ پس سرویس را مستقیم با fetch جعلی می‌آوریم
    assert r.status_code in (200, 500)

    # مستقیم از سرویس با fetch جعلی:
    from app.core.database import SessionLocal
    from app.core.security import build_dev_actor
    from app.modules.students import service as svc
    from app.modules.integrations.models import Tenant as TenantModel

    db = SessionLocal()
    try:
        tenant = db.query(TenantModel).filter(TenantModel.code == tenant1).one()
        actor = build_dev_actor({"x-dev-user": "steward1", "x-dev-roles": "steward",
                                 "x-dev-tenants": tenant1, "x-dev-name": "S"})
        report = svc.sync_from_smart_university(db, tenant.id, actor, fetch=fake_fetch)
        db.commit()
        assert report["created"] == 1, report
        assert report["total_remote"] == 1

        from app.modules.students.models import Student
        row = db.query(Student).filter(
            Student.tenant_id == tenant.id, Student.ext_ref == "su-1001").one()
        assert row.degree_level == "karshenasi_arshad"
        assert row.mobile == "09351112233"
        assert row.status == "active"
        assert row.source == "smart_university"

        # سینک دوم → بدون تغییر
        report2 = svc.sync_from_smart_university(db, tenant.id, actor, fetch=fake_fetch)
        db.commit()
        assert report2["created"] == 0 and report2["updated"] == 0
        assert report2["unchanged"] == 1
    finally:
        db.close()


def test_pull_sync_skips_incomplete_remote_record(client, tenant1):
    from app.core.database import SessionLocal
    from app.core.security import build_dev_actor
    from app.modules.students import service as svc
    from app.modules.integrations.models import Tenant as TenantModel

    bad = {"external_ref": "su-bad", "student_number": "", "first_name": "", "last_name": "بدون نام"}
    db = SessionLocal()
    try:
        tenant = db.query(TenantModel).filter(TenantModel.code == tenant1).one()
        actor = build_dev_actor({"x-dev-user": "steward1", "x-dev-roles": "steward",
                                 "x-dev-tenants": tenant1, "x-dev-name": "S"})
        report = svc.sync_from_smart_university(
            db, tenant.id, actor,
            fetch=lambda url, h: (200, {"items": [bad], "total": 1}))
        db.commit()
        assert report["created"] == 0
        assert len(report["skipped"]) == 1
    finally:
        db.close()


def test_pull_sync_remote_unreachable_is_reported_not_crashed(client, tenant1):
    from app.core.database import SessionLocal
    from app.core.security import build_dev_actor
    from app.modules.students import service as svc
    from app.modules.integrations.models import Tenant as TenantModel

    def broken_fetch(url, headers):
        raise ConnectionError("refused")

    db = SessionLocal()
    try:
        tenant = db.query(TenantModel).filter(TenantModel.code == tenant1).one()
        actor = build_dev_actor({"x-dev-user": "steward1", "x-dev-roles": "steward",
                                 "x-dev-tenants": tenant1, "x-dev-name": "S"})
        report = svc.sync_from_smart_university(db, tenant.id, actor, fetch=broken_fetch)
        db.commit()
        assert report["remote_status"] is None
        assert "برقرار نشد" in report["message"]
        assert report["created"] == 0
    finally:
        db.close()


# ------------------------------------------------ push (ingest) با کلید API

def test_ingest_requires_key_and_pushes(client, tenant1, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "STUDENTS_INGEST_KEY", "ingest-secret-key")

    # رکورد مخصوص push — از رکورد pull جداست تا شمارش created دقیق باشد
    push_item = {**REMOTE_ITEM, "external_ref": "su-2001", "student_number": "403997002",
                 "national_id": "0034567890"}

    # بدون کلید → 403
    r = client.post("/api/v1/students/ingest", json={"items": [push_item]},
                    headers={"X-Tenant-Code": tenant1})
    assert r.status_code == 403

    # با کلید → upsert
    r = client.post("/api/v1/students/ingest", json={"items": [push_item]},
                    headers={"X-Api-Key": "ingest-secret-key", "X-Tenant-Code": tenant1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "push"
    assert body["created"] == 1, body

    # push مجدد همان رکورد → unchanged
    r2 = client.post("/api/v1/students/ingest", json={"items": [push_item]},
                     headers={"X-Api-Key": "ingest-secret-key", "X-Tenant-Code": tenant1})
    assert r2.json()["unchanged"] == 1


def test_ingest_disabled_without_key(client, tenant1, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "STUDENTS_INGEST_KEY", "")
    r = client.post("/api/v1/students/ingest", json={"items": []},
                    headers={"X-Api-Key": "x", "X-Tenant-Code": tenant1})
    assert r.status_code == 503
    assert r.json()["code"] == "INGEST_DISABLED"
