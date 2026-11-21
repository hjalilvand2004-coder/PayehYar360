"""آزمون‌های اطلاعات پایه چندسامانه‌ای v1.0.7: تاریخ شمسی، درج/همگام‌سازی، کلید سرویس و لاگ."""
from tests.conftest import dev_headers


def test_jalali_conversion():
    from app.common.jalali import gregorian_to_jalali, jalali_str, jalali_to_gregorian
    assert gregorian_to_jalali(2026, 3, 21) == (1405, 1, 1)   # نوروز ۱۴۰۵
    assert gregorian_to_jalali(2024, 3, 20) == (1403, 1, 1)   # نوروز ۱۴۰۳
    assert gregorian_to_jalali(2026, 11, 21) == (1405, 8, 30)
    assert gregorian_to_jalali(2026, 11, 22) == (1405, 9, 1)
    j = gregorian_to_jalali(2025, 9, 22)
    assert jalali_to_gregorian(*j) == (2025, 9, 22)
    assert jalali_str("2026-11-22T10:00:00", with_time=True) == "۱۴۰۵/۰۹/۰۱ ۱۰:۰۰"


def test_instructor_import_and_service_flow(client, tenant1):
    h = dev_headers(tenant=tenant1)
    r = client.post("/api/v1/masterdata/import/instructors", json={"items": [
        {"id": 12, "name": "دکتر سارا موسوی", "academic_rank": "استاد تمام", "department": "ریاضی"},
        {"code": "P2", "instructor_name": "دکتر رضا کریمی"},
    ]}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["total"] == 2
    r = client.get("/api/v1/masterdata/instructors", headers=h)
    names = [i["full_name"] for i in r.json()["items"]]
    assert "دکتر سارا موسوی" in names
    # ایجاد کلاینت سرویس و کلید API (فقط یک‌بار نمایش)
    r = client.post("/api/v1/masterdata/service-clients",
                    json={"code": "edu", "title": "سامانه آموزش",
                          "scopes": ["instructors", "classrooms"]}, headers=h)
    assert r.status_code == 201, r.text
    key = r.json()["api_key"]
    assert key.startswith("pyk_")
    # واکشی با کلید — تاریخ شمسی در پاسخ
    r = client.get("/api/v1/services/masterdata/instructors", headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["count"] == 2 and data["domain"] == "instructors"
    assert "generated_at_jalali" in data
    # لاگ واکشی ثبت شده با زمان شمسی
    r = client.get("/api/v1/masterdata/fetch-logs?direction=out", headers=h)
    logs = r.json()["items"]
    assert any(l["domain"] == "instructors" and l["client_code"] == "edu" and l["record_count"] == 2
               for l in logs)
    assert "/" in logs[0]["occurred_at_jalali"]
    # کلید غلط → 401
    r = client.get("/api/v1/services/masterdata/instructors", headers={"X-API-Key": "pyk_bad"})
    assert r.status_code == 401
    # دامنه خارج از scope → 403
    r = client.get("/api/v1/services/masterdata/organizations", headers={"X-API-Key": key})
    assert r.status_code == 403
    # قطع دسترسی → 401
    client_id = r2 = None
    r2 = client.get("/api/v1/masterdata/service-clients", headers=h)
    cid = [c for c in r2.json()["items"] if c["code"] == "edu"][0]["id"]
    r = client.post(f"/api/v1/masterdata/service-clients/{cid}/revoke", headers=h)
    assert r.status_code == 200
    r = client.get("/api/v1/services/masterdata/instructors", headers={"X-API-Key": key})
    assert r.status_code == 401


def test_classroom_import(client, tenant1):
    h = dev_headers(tenant=tenant1)
    r = client.post("/api/v1/masterdata/import/classrooms", json={"items": [
        {"id": 1, "name": "کلاس ۲۰۱", "room_type": "کلاس", "capacity": 40, "building": "ساختمان مرکزی"},
        {"id": 2, "name": "سالن همایش فردوسی", "room_type": "سالن", "capacity": 300},
    ]}, headers=h)
    assert r.status_code == 201, r.text
    r = client.get("/api/v1/masterdata/classrooms", headers=h)
    items = r.json()["items"]
    assert len(items) == 2
    caps = {i["capacity"] for i in items}
    assert {40, 300} <= caps
    kinds = {i["kind"] for i in items}
    assert "کلاس" in kinds and "سالن" in kinds


def test_sync_not_configured(client, tenant1):
    r = client.post("/api/v1/masterdata/sync/instructors", headers=dev_headers(tenant=tenant1))
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "SOURCE_NOT_CONFIGURED"


def test_catalog(client, tenant1):
    r = client.get("/api/v1/masterdata/catalog", headers=dev_headers(tenant=tenant1))
    data = r.json()
    domains = {i["domain"] for i in data["items"]}
    assert {"instructors", "classrooms", "organizations", "unique-courses",
            "reference-items"} <= domains
    instructors = [i for i in data["items"] if i["domain"] == "instructors"][0]
    assert instructors["count"] >= 2
    assert instructors["last_sync"]["at_jalali"]
