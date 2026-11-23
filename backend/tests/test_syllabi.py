"""آزمون‌های سرفصل‌های مصوب دروس v1.0.9: ایمپورت idempotent، جستجو/فیلتر، جزئیات،
آمار، و سرویس‌دهی به سایر سامانه‌ها با کلید API (دامنه course-syllabi)."""
from tests.conftest import dev_headers

CE_ITEM = {
    "source_set": "CE403", "source_file": "Advanced Logic Design.pdf",
    "title_fa": "مدارهای منطقی پیشرفته", "title_en": "Advanced Logic Design",
    "course_code": "CSE-313", "course_type": "نظری، اختیاری",
    "unit_theory": 3, "hour_theory": 48,
    "prerequisites": "مدارهای منطقی",
    "general_goal": "آشنا کردن دانشجویان با مفاهیم طراحی مدارات همگام و غیرهمگام",
    "evaluation": "آزمون میانترم و پایانی",
    "references": "[1] LaMeres. Introduction to logic circuits.",
    "topics": [
        {"seq": 1, "title": "مرور مدارهای ترتیبی"},
        {"seq": 2, "title": "طراحی مدارهای ترتیبی همگام", "hours": 4},
        {"seq": 3, "title": "مدارهای ترتیبی ناهمگام"},
    ],
}

NP_ITEM = {
    "source_set": "NP1400", "source_file": "Cloud Computing.pdf",
    "title_fa": "رایانش ابری", "title_en": "Cloud Computing",
    "course_code": "28-3", "course_type": "اختیاری",
    "unit_theory": 2, "unit_practice": 1, "hour_theory": 32, "hour_practice": 32,
    "general_goal": "شناخت مفاهیم کلیدی و پایه‌ای در رایانش ابری",
    "topics": [
        {"seq": 1, "title": "معرفی رایانش ابری، مفاهیم اساسی", "hours": 4, "hours_practice": None},
        {"seq": 2, "title": "چارچوب NIST و مدل‌های تحویل ابر", "hours": 3},
    ],
}


def test_syllabus_import_list_detail_stats(client, tenant1):
    h = dev_headers(tenant=tenant1)
    # ایمپورت دو سرفصل از دو مجموعه
    r = client.post("/api/v1/masterdata/import/syllabi", json={"items": [CE_ITEM, NP_ITEM]},
                    headers=h)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["total"] == 2 and out["created"] == 2 and out["skipped"] == 0

    # ایمپورت مجدد همان فایل‌ها → بروزرسانی (idempotent)
    r = client.post("/api/v1/masterdata/import/syllabi", json={"items": [CE_ITEM, NP_ITEM]},
                    headers=h)
    assert r.status_code == 201
    assert r.json()["updated"] == 2 and r.json()["created"] == 0

    # فهرست + جستجو + فیلتر مجموعه
    r = client.get("/api/v1/masterdata/syllabi", headers=h)
    items = r.json()["items"]
    assert len(items) == 2
    assert all(i["topics_count"] >= 2 for i in items)
    r = client.get("/api/v1/masterdata/syllabi?search=منطقی", headers=h)
    assert len(r.json()["items"]) == 1
    r = client.get("/api/v1/masterdata/syllabi?source_set=NP1400", headers=h)
    assert [i["title_en"] for i in r.json()["items"]] == ["Cloud Computing"]

    # جزئیات با سرفصل‌ها به ترتیب
    sid = items[0]["id"]
    r = client.get(f"/api/v1/masterdata/syllabi/{sid}", headers=h)
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["course_code"] in ("CSE-313", "28-3")
    seqs = [t["seq"] for t in detail["topics"]]
    assert seqs == sorted(seqs) and len(seqs) >= 2
    assert any(t.get("hours") for t in detail["topics"])

    # آمار
    r = client.get("/api/v1/masterdata/syllabi-stats", headers=h)
    stats = r.json()
    assert stats["total"] == 2
    assert stats["by_set"]["CE403"] == 1 and stats["by_set"]["NP1400"] == 1
    assert stats["topics_total"] == 5
    assert "1394" in stats["sets_labels"]

    # بدون احراز → 401
    r = client.get("/api/v1/masterdata/syllabi")
    assert r.status_code == 401

    # ردیف بدون هیچ عنوانی → skipped
    r = client.post("/api/v1/masterdata/import/syllabi", json={"items": [{"course_code": "X-1"}]},
                    headers=h)
    assert r.status_code == 201 and r.json()["skipped"] == 1

    # لاگ همگام‌سازی ثبت شده
    r = client.get("/api/v1/masterdata/fetch-logs?domain=course-syllabi&direction=in", headers=h)
    logs = r.json()["items"]
    assert logs and logs[0]["source"] == "manual" and logs[0]["record_count"] >= 2


def test_syllabus_service_domain_for_other_systems(client, tenant1):
    h = dev_headers(tenant=tenant1)
    client.post("/api/v1/masterdata/import/syllabi", json={"items": [CE_ITEM]}, headers=h)
    # کلاینت سرویس فقط برای دامنه course-syllabi
    r = client.post("/api/v1/masterdata/service-clients",
                    json={"code": "sylconsumer", "title": "مصرف‌کننده سرفصل",
                          "scopes": ["course-syllabi"]}, headers=h)
    assert r.status_code == 201, r.text
    key = r.json()["api_key"]

    # واکشی دامنه سرفصل‌ها با کلید API
    r = client.get("/api/v1/services/masterdata/course-syllabi", headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] and data["domain"] == "course-syllabi"
    assert data["count"] >= 1
    it = next(x for x in data["items"] if x["title_en"] == "Advanced Logic Design")
    assert it["units"]["theory"] == 3 and it["hours"]["theory"] == 48
    assert len(it["topics"]) == 3 and it["topics"][0]["title"] == "مرور مدارهای ترتیبی"
    assert "generated_at_jalali" in data

    # دلتا با since آینده → خالی
    r = client.get("/api/v1/services/masterdata/course-syllabi?since=2099-01-01T00:00:00",
                   headers={"X-API-Key": key})
    assert r.json()["count"] == 0

    # کلاینت به دامنه دیگر (محدود به scope) → 403
    r = client.get("/api/v1/services/masterdata/instructors", headers={"X-API-Key": key})
    assert r.status_code == 403

    # کاتالوگ، دامنه جدید را با شمارش نشان می‌دهد
    r = client.get("/api/v1/masterdata/catalog", headers=h)
    domains = {d["domain"]: d["count"] for d in r.json()["items"]}
    assert domains.get("course-syllabi", 0) >= 1
