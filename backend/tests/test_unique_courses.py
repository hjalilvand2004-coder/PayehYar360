"""آزمون‌های زنجیره درس: درس یکتا ← درس تفکیکی (۱ تا ۳) ← سرفصل مصوب."""
import pytest

from tests.conftest import dev_headers

ROWS = [
    {"row": "1", "title": "ریاضی عمومی 1", "unique_code": "1044", "section": "پایه",
     "year": "1403", "type": "پیوسته", "unit_theory": "3", "unit_practice": "—",
     "prereq": "-", "capacity": "30"},
    {"row": "2", "title": "ریاضی عمومی 1", "unique_code": "1044", "section": "پایه",
     "year": "1394", "type": "پیوسته", "unit_theory": "3", "unit_practice": "—",
     "prereq": "-", "capacity": "30"},
    {"row": "3", "title": "طراحی الگوریتم ها", "unique_code": "1058", "section": "تخصصی",
     "year": "1403", "type": "پیوسته", "unit_theory": "3", "unit_practice": "—",
     "prereq": "داده ساختارها و الگوریتم ها", "capacity": "30"},
    {"row": "4", "title": "طراحی الگوریتم", "unique_code": "1058", "section": "تخصصی",
     "year": "ناپیوسته", "type": "ناپیوسته", "unit_theory": "3", "unit_practice": "—",
     "prereq": "-", "capacity": "30"},
    {"row": "5", "title": "طراحی الگوریتم ها", "unique_code": "1058", "section": "تخصصی",
     "year": "1394", "type": "پیوسته", "unit_theory": "3", "unit_practice": "—",
     "prereq": "داده ساختارها و الگوریتم ها", "capacity": "30"},
]


def test_unique_split_import_and_chain(client, tenant1):
    h = dev_headers(tenant=tenant1)
    # ایمپورت درس‌یار — هر ردیف یک درس تفکیکی است؛ درس یکتا از کد یکتا ساخته می‌شود
    r = client.post("/api/v1/masterdata/import/darsyar-courses", json={"rows": ROWS}, headers=h)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["created_unique"] == 2 and out["created_split"] == 5 and out["skipped"] == 0
    # ایمپورت مجدد → idempotent
    r = client.post("/api/v1/masterdata/import/darsyar-courses", json={"rows": ROWS}, headers=h)
    assert r.json()["created_unique"] == 0 and r.json()["created_split"] == 0

    # فهرست درس یکتا + شمارش زنجیره
    r = client.get("/api/v1/masterdata/unique-courses", headers=h)
    assert r.status_code == 200 and r.json()["total"] == 2
    items = r.json()["items"]
    alg = next(i for i in items if i["code"] == "1058")
    math = next(i for i in items if i["code"] == "1044")
    assert alg["split_count"] == 3 and alg["chain_ok"] is True
    assert math["split_count"] == 2 and math["chain_ok"] is False  # قاعده: ۱ یا ۳

    # جزئیات + تفکیکی‌های یک درس یکتا (تفکیک با سال/مجموعه)
    r = client.get(f"/api/v1/masterdata/unique-courses/{alg['id']}/split-courses", headers=h)
    splits = r.json()["items"]
    assert len(splits) == 3
    keys = {(s["year_label"], s["cohort_set"]) for s in splits}
    assert {("1403", "پیوسته"), ("1394", "پیوسته"), (None, "ناپیوسته")} <= keys

    # درج دستی درس یکتا + کد تکراری → 409
    r = client.post("/api/v1/masterdata/unique-courses", headers=h,
                    json={"code": "9001", "title_fa": "درس آزمایشی", "section": "اصلی",
                          "unit_theory": 2})
    assert r.status_code == 201, r.text
    uc_id = r.json()["id"]
    r = client.post("/api/v1/masterdata/unique-courses", headers=h,
                    json={"code": "9001", "title_fa": "تکراری"})
    assert r.status_code == 409

    # ویرایش درس یکتا
    r = client.patch(f"/api/v1/masterdata/unique-courses/{uc_id}", headers=h,
                     json={"title_en": "Test Course", "capacity": 40})
    assert r.status_code == 200 and r.json()["capacity"] == 40

    # درج دستی درس تفکیکی (فال‌بک عنوان درس یکتا) + تکراری → 409
    r = client.post("/api/v1/masterdata/split-courses", headers=h,
                    json={"unique_course_id": uc_id, "year_label": "1403", "cohort_set": "پیوسته"})
    assert r.status_code == 201, r.text
    sc_id = r.json()["id"]
    assert r.json()["title"] == "درس آزمایشی"
    r = client.post("/api/v1/masterdata/split-courses", headers=h,
                    json={"unique_course_id": uc_id, "year_label": "1403", "cohort_set": "پیوسته"})
    assert r.status_code == 409

    # حذف درس یکتا با تفکیکی → 409 (ترتیب زنجیره محفوظ است)
    r = client.delete(f"/api/v1/masterdata/unique-courses/{uc_id}", headers=h)
    assert r.status_code == 409

    # نقش بدون دسترسی → 403
    r = client.post("/api/v1/masterdata/unique-courses",
                    headers=dev_headers(tenant=tenant1, roles="auditor"),
                    json={"code": "9002", "title_fa": "x"})
    assert r.status_code == 403


def test_syllabus_chain_link_and_filters(client, tenant1):
    h = dev_headers(tenant=tenant1)
    client.post("/api/v1/masterdata/import/darsyar-courses", json={"rows": ROWS}, headers=h)
    # سرفصل هم‌عنوان → باید با اتصال خودکار به تفکیکی ۱۴۰۳ پیوسته متصل شود
    client.post("/api/v1/masterdata/import/syllabi", headers=h, json={"items": [
        {"source_set": "CE403", "source_file": "Algo.pdf", "title_en": "Algorithm Design",
         "title_fa": "طراحی الگوریتم ها", "topics": [{"title": "پیچیدگی"}]},
    ]})
    r = client.post("/api/v1/masterdata/syllabi/auto-link", headers=h)
    assert r.status_code == 200 and r.json()["linked"] == 1, r.text

    r = client.get("/api/v1/masterdata/syllabi?search=الگوریتم", headers=h)
    items = r.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["split_course"]["year_label"] == "1403"
    assert row["unique_course"]["code"] == "1058"
    sid = row["id"]

    # اتصال دستی به تفکیکی ۱۳۹۴ + فیلتر فهرست
    splits = client.get("/api/v1/masterdata/split-courses", headers=h).json()["items"]
    target = next(s for s in splits if s["year_label"] == "1394")
    r = client.patch(f"/api/v1/masterdata/syllabi/{sid}", headers=h,
                     json={"split_course_id": target["id"]})
    assert r.status_code == 200 and r.json()["split_course"]["id"] == target["id"]
    r = client.get(f"/api/v1/masterdata/syllabi?split_course_id={target['id']}", headers=h)
    assert [i["id"] for i in r.json()["items"]] == [sid]
    r = client.get(f"/api/v1/masterdata/split-courses/{target['id']}/syllabi", headers=h)
    assert [i["id"] for i in r.json()["items"]] == [sid]

    # جست‌وجوی تفکیکی با عنوان درس یکتا (join)
    r = client.get("/api/v1/masterdata/split-courses?search=الگوریتم", headers=h)
    assert r.json()["total"] == 3  # پیوسته ۱۴۰۳ + پیوسته ۱۳۹۴ + ناپیوسته

    # تفکیکی ناموجود → 404؛ خارج کردن پیوند با null
    r = client.patch(f"/api/v1/masterdata/syllabi/{sid}", headers=h,
                     json={"split_course_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 404
    r = client.patch(f"/api/v1/masterdata/syllabi/{sid}", headers=h, json={"split_course_id": None})
    assert r.status_code == 200 and r.json()["split_course"] is None
    client.post("/api/v1/masterdata/syllabi/auto-link", headers=h)

    # حذف تفکیکی → سرفصل متصل جدا می‌شود (حذف نمی‌شود)
    client.patch(f"/api/v1/masterdata/syllabi/{sid}", headers=h, json={"split_course_id": target["id"]})
    r = client.delete(f"/api/v1/masterdata/split-courses/{target['id']}", headers=h)
    assert r.status_code == 200 and r.json()["unlinked_syllabi"] == 1
    r = client.get(f"/api/v1/masterdata/syllabi/{sid}", headers=h)
    assert r.json()["split_course"] is None

    # بررسی‌های کیفیت حوزه زنجیره + دامنه‌های سرویس
    r = client.get("/api/v1/quality/overview", headers=h)
    dom = next(d for d in r.json()["domains"] if d["key"] == "chain")
    assert dom["checks"] >= 3
    r = client.get("/api/v1/masterdata/catalog", headers=h)
    domains = {i["domain"] for i in r.json()["items"]}
    assert {"unique-courses", "split-courses"} <= domains
