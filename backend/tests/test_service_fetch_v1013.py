"""تست‌های v1.0.13 — سرویس‌دهی به سامانه یادگیری هوشمند (دانشجو۳۶۰ v3.4.0).

پوشش:
- رفع باگ واقعی استقرار: واکشی دامنه split-courses با «NameError: name 'uc' is
  not defined» (500) شکست می‌خورد — ترتیب‌دهی باید پیش از ارزیابی comprehension
  با ویژگی کلاس ORM انجام شود، نه با متغیرهای حلقه.
- نام جایگزین «syllabi» = «course-syllabi» (قرارداد سند فنی اتصال).
- ETag / If-None-Match → 304 و باطل شدن ETag پس از تغییر داده.
- دلتای since طبق راهنمای یکپارچه‌سازی.
"""
import pytest

from tests.conftest import dev_headers


@pytest.fixture(scope="session")
def svc_tenant(client) -> str:
    """tenant اختصاصی این ماژول — تا داده آزمون، شمارش‌های تست زنجیره درس را به‌هم نزند."""
    r = client.post("/api/v1/tenants", json={"code": "tsvc", "name": "دانشگاه سرویس‌گیرنده"},
                    headers=dev_headers(tenant="tsvc"))
    assert r.status_code == 201, r.text
    return "tsvc"


def _setup_courses(client, tenant) -> str:
    """داده آزمون + کلید سرویس با دسترسی سه دامنه — یک‌بار در نشست (کلید فقط یک‌بار نمایش داده می‌شود)."""
    h = dev_headers(tenant=tenant, roles="steward,tenant_admin,master_data_editor")
    r = client.get("/api/v1/masterdata/unique-courses", headers=h)
    assert r.status_code == 200, r.text
    items = [i for i in r.json()["items"] if i["code"] == "UC101"]
    if not items:
        r = client.post("/api/v1/masterdata/unique-courses",
                        json={"code": "UC101", "title_fa": "ریاضیات گسسته",
                              "section": "اصلی", "unit_theory": 3, "unit_practice": 1},
                        headers=h)
        assert r.status_code == 201, r.text
        items = [i for i in client.get("/api/v1/masterdata/unique-courses",
                                       headers=h).json()["items"] if i["code"] == "UC101"]
    uc_id = items[0]["id"]
    r = client.get("/api/v1/masterdata/split-courses", headers=h)
    splits = [i for i in r.json()["items"] if i.get("unique_course_id") == uc_id]
    if not splits:
        r = client.post("/api/v1/masterdata/split-courses",
                        json={"unique_course_id": uc_id, "year_label": "1403",
                              "cohort_set": "پایه‌یازدهم", "unit_theory": 3},
                        headers=h)
        assert r.status_code == 201, r.text
    r = client.post("/api/v1/masterdata/service-clients",
                    json={"code": "smart360", "title": "سامانه یادگیری هوشمند",
                          "scopes": ["unique-courses", "split-courses", "course-syllabi"]},
                    headers=h)
    if r.status_code == 409:  # کلاینت قبلاً در نشست ساخته شده — کلید دوباره نمایش داده نمی‌شود
        pytest.skip("کلید سرویس smart360 در این نشست قبلاً صادر شده است")
    assert r.status_code == 201, r.text
    return r.json()["api_key"]


@pytest.fixture(scope="session")
def smart_key(client, svc_tenant) -> str:
    return _setup_courses(client, svc_tenant)


def test_split_courses_service_domain_no_nameerror(client, svc_tenant, smart_key):
    # پیش از رفع باگ همین فراخوانی 500 با «NameError: name 'uc' is not defined» می‌داد
    r = client.get("/api/v1/services/masterdata/split-courses",
                   headers={"X-API-Key": smart_key})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["domain"] == "split-courses" and data["count"] >= 1
    item = data["items"][0]
    assert item["unique_course_code"] == "UC101"
    assert item["parent_code"] == "UC101"
    assert item["attrs"]["year_label"] == "1403"


def test_syllabi_alias_matches_course_syllabi(client, svc_tenant, smart_key):
    r1 = client.get("/api/v1/services/masterdata/course-syllabi",
                    headers={"X-API-Key": smart_key})
    r2 = client.get("/api/v1/services/masterdata/syllabi",
                    headers={"X-API-Key": smart_key})
    assert r1.status_code == 200 and r2.status_code == 200, r1.text
    a, b = r1.json(), r2.json()
    assert a["domain"] == "course-syllabi" and b["domain"] == "course-syllabi"
    assert b.get("requested_domain") == "syllabi"
    assert a["count"] == b["count"] and a["items"] == b["items"]


def test_etag_and_304_invalidation(client, svc_tenant, smart_key):
    r = client.get("/api/v1/services/masterdata/unique-courses",
                   headers={"X-API-Key": smart_key})
    assert r.status_code == 200
    etag = r.headers.get("ETag")
    assert etag
    # بدون تغییر → 304 بدون بدنه
    r2 = client.get("/api/v1/services/masterdata/unique-courses",
                    headers={"X-API-Key": smart_key, "If-None-Match": etag})
    assert r2.status_code == 304 and r2.headers.get("ETag") == etag
    # تغییر داده → ETag باطل → پاسخ کامل با داده جدید
    h = dev_headers(tenant=svc_tenant, roles="steward,tenant_admin,master_data_editor")
    r = client.post("/api/v1/masterdata/unique-courses",
                    json={"code": "UC102", "title_fa": "ساختمان داده"}, headers=h)
    assert r.status_code == 201, r.text
    r3 = client.get("/api/v1/services/masterdata/unique-courses",
                    headers={"X-API-Key": smart_key, "If-None-Match": etag})
    assert r3.status_code == 200 and r3.headers.get("ETag") != etag
    assert r3.json()["count"] >= 2


def test_since_delta(client, svc_tenant, smart_key):
    r = client.get("/api/v1/services/masterdata/unique-courses?since=2099-01-01T00:00:00",
                   headers={"X-API-Key": smart_key})
    assert r.status_code == 200 and r.json()["count"] == 0


def test_scope_forbidden_still_enforced(client, svc_tenant, smart_key):
    r = client.get("/api/v1/services/masterdata/organizations",
                   headers={"X-API-Key": smart_key})
    assert r.status_code == 403
