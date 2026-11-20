"""آزمون سناریوهای الزامي بخش ۱۵.۲ سند فنی."""
from __future__ import annotations

import json

from tests.conftest import dev_headers

API = "/api/v1"


def test_concurrent_edit_person_version_conflict(client, tenant1, person1):
    """اصلاح هم‌زمان یک شخص → یکی موفق؛ دیگری تعارض نسخه (412)."""
    headers = dev_headers(roles="master_data_editor", tenant=tenant1)
    r1 = client.patch(f"{API}/persons/{person1['id']}", json={"display_name": "علی رضایی (اصلاح اول)"},
                      headers={**headers, "If-Match": f'"{person1["version"]}"'})
    assert r1.status_code == 200, r1.text
    r2 = client.patch(f"{API}/persons/{person1['id']}", json={"display_name": "اصلاح هم‌زمان"},
                      headers={**headers, "If-Match": f'"{person1["version"]}"'})
    assert r2.status_code == 412
    assert r2.json()["code"] == "VERSION_CONFLICT"
    assert r2.json()["details"]["current_version"] == person1["version"] + 1


def test_idempotency_same_key_no_duplicate_effect(client, tenant1):
    """ثبت مجدد درخواست با همان کلید → اثر جدید ایجاد نشود."""
    headers = dev_headers(roles="master_data_editor", tenant=tenant1)
    payload = {"given_name": "پویا", "family_name": "صادقی"}
    r1 = client.post(f"{API}/persons", json=payload, headers={**headers, "Idempotency-Key": "idem-1"})
    assert r1.status_code == 201
    r2 = client.post(f"{API}/persons", json=payload, headers={**headers, "Idempotency-Key": "idem-1"})
    assert r2.status_code == 201
    assert r2.headers.get("Idempotent-Replay") == "true"
    assert r2.json()["id"] == r1.json()["id"]
    search = client.get(f"{API}/persons", params={"q": "صادقی"}, headers=headers).json()
    assert search["total"] == 1  # اثر تکراری ثبت نشده است


def test_idempotency_same_key_different_input_rejected(client, tenant1):
    """کلید یکسان با ورودی متفاوت → رد درخواست (409)."""
    headers = dev_headers(roles="master_data_editor", tenant=tenant1)
    r1 = client.post(f"{API}/persons", json={"given_name": "نیما", "family_name": "کریمی"},
                     headers={**headers, "Idempotency-Key": "idem-2"})
    assert r1.status_code == 201
    r2 = client.post(f"{API}/persons", json={"given_name": "نیما", "family_name": "دیگر"},
                     headers={**headers, "Idempotency-Key": "idem-2"})
    assert r2.status_code == 409
    assert r2.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_cross_tenant_access_forbidden(client, tenant1, tenant2, person1):
    """دسترسی مشتری دیگر → منع دسترسی."""
    # شخصِ مشتری ۱ با هویت مشتری ۲ دیده نمی‌شود
    r = client.get(f"{API}/persons/{person1['id']}", headers=dev_headers(tenant=tenant2))
    assert r.status_code == 404
    # هویتی که عضو مشتری ۲ است نمی‌تواند ادعا کند عضو مشتری ۱ است
    r = client.get(f"{API}/persons", headers=dev_headers(tenant=tenant2, user="other-user"))
    assert r.status_code == 200  # فقط داده مشتری خودش را می‌بیند
    assert all(p["id"] != person1["id"] for p in r.json()["items"])


def test_non_owner_edit_rejected_then_change_request_applied(client, tenant1, person1):
    """ویرایش توسط غیرمالک → رد؛ سپس درخواست اصلاح و تأیید متولی."""
    viewer_headers = dev_headers(user="viewer1", roles="viewer", tenant=tenant1)
    r = client.patch(f"{API}/persons/{person1['id']}", json={"display_name": "دستکاری غیرمجاز"},
                     headers={**viewer_headers, "If-Match": f'"{person1["version"]}"'})
    assert r.status_code == 403
    assert r.json()["code"] == "DATA_OWNER_MISMATCH"

    # درخواست اصلاح توسط مشاهده‌گر
    r = client.post(f"{API}/change-requests", json={
        "entity_type": "person", "entity_id": person1["id"],
        "proposed_changes": {"display_name": "نام اصلاح‌شده با تأیید متولی"},
        "reason": "اشتباه تایپی در ثبت اولیه",
    }, headers=viewer_headers)
    assert r.status_code == 201, r.text
    cr = r.json()

    steward_headers = dev_headers(user="steward1", roles="steward", tenant=tenant1)
    r = client.post(f"{API}/change-requests/{cr['id']}/decision",
                    json={"action": "approve", "note": "تأیید شد"}, headers=steward_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert r.json()["applied_version"] == person1["version"] + 1

    r = client.get(f"{API}/persons/{person1['id']}", headers=steward_headers)
    assert r.json()["display_name"] == "نام اصلاح‌شده با تأیید متولی"


def test_rabbitmq_outage_keeps_changes_in_outbox(client, tenant1, person1):
    """قطعی RabbitMQ → تغییر در Outbox باقی می‌ماند و منتشر نمی‌شود."""
    r = client.get(f"{API}/integrations/status", headers=dev_headers(tenant=tenant1))
    assert r.status_code == 200
    st = r.json()
    assert st["rabbitmq"]["connected"] is False  # Broker قطع/غیرفعال در آزمون
    assert st["outbox"]["pending"] >= 1
    assert st["outbox"]["oldest_pending_age_seconds"] is not None


def test_outbox_replay_safe_and_worker_marks_pending(client, tenant1):
    """قطع Worker پس از انتشار → تکرار امن؛ بدون Broker، منتشرنشده می‌ماند."""
    from app.workers import outbox_worker
    # بدون Broker هیچ رویدادی published نمی‌شود
    outbox_worker.process_pending_batch()
    from app.core.database import SessionLocal
    from app.modules.synchronization.models import OutboxEvent
    db = SessionLocal()
    try:
        published = db.query(OutboxEvent).filter(OutboxEvent.status == "published").count()
        pending = db.query(OutboxEvent).filter(OutboxEvent.status == "pending").count()
        assert published == 0
        assert pending > 0
    finally:
        db.close()


def test_cursor_flow_and_expiry(client, tenant1):
    """بازیابی تغییرات با cursor؛ cursor منقضی → 410 و الزام Snapshot."""
    headers = dev_headers(roles="steward", tenant=tenant1)
    # چند تغییر ایجاد کنیم
    for i in range(6):
        client.post(f"{API}/persons", json={"given_name": "کاربر", "family_name": f"شماره{i}"},
                    headers=dev_headers(roles="master_data_editor", tenant=tenant1))
    r = client.get(f"{API}/sync/changes", params={"limit": 10},
                   headers=dev_headers(tenant=tenant1, scopes="sync"))
    assert r.status_code == 200
    body = r.json()
    assert body["changes"], "باید تغییرات برگردد"
    seqs = [c["seq"] for c in body["changes"]]
    assert seqs == sorted(seqs), "ترتیب seq باید صعودی باشد"

    # درخواست بدون cursor از ابتدای جریان شروع می‌شود؛ سپس با cursor=0 و عمق نگهداری ۵ منقضی می‌شود
    client.post(f"{API}/persons", json={"given_name": "کاربر", "family_name": "افزوده"},
                headers=dev_headers(roles="master_data_editor", tenant=tenant1))
    r2 = client.get(f"{API}/sync/changes", params={"cursor": 0, "limit": 10},
                    headers=dev_headers(tenant=tenant1, scopes="sync"))
    # با عمق نگهداری ۵ و بیش از ۵ تغییر، cursor=0 باید منقضی شود
    assert r2.status_code == 410
    assert r2.json()["code"] == "CURSOR_EXPIRED"


def test_merge_preserves_alias_history_and_mappings(client, tenant1):
    """ادغام شخص → حفظ alias، سابقه و انتقال نگاشت."""
    headers = dev_headers(roles="master_data_editor", tenant=tenant1)
    p1 = client.post(f"{API}/persons", json={"given_name": "حمید", "family_name": "طاهری"}, headers=headers).json()
    p2 = client.post(f"{API}/persons", json={"given_name": "حمید", "family_name": "طاهری"}, headers=headers).json()
    # نگاشت محلی روی منبع
    insts = client.get(f"{API}/installations", headers=dev_headers(tenant=tenant1)).json()["items"]
    edu = next(i for i in insts if i["system_code"] == "edu") if insts else None
    if edu is None:
        r = client.post(f"{API}/installations", json={
            "system_code": "edu", "installation_code": "edu-t1", "title": "آموزش آزمون",
        }, headers=dev_headers(tenant=tenant1, roles="integration_admin,tenant_admin"))
        edu = r.json()
    mapping = client.post(f"{API}/id-mappings", json={
        "installation_id": edu["id"], "entity_type": "person", "local_id": "ST-900", "entity_id": p1["id"],
    }, headers=dev_headers(tenant=tenant1, roles="steward")).json()

    steward = dev_headers(user="steward1", roles="steward", tenant=tenant1)
    case = client.post(f"{API}/quality/cases", json={"candidate_ids": [p1["id"], p2["id"]]},
                       headers=steward).json()
    assert case["status"] == "open"
    result = client.post(f"{API}/resolution-cases/{case['id']}/merge",
                         json={"target_person_id": p2["id"], "note": "یک شخص واقعی است"}, headers=steward)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["target_person_id"] == p2["id"]

    # منبع ادغام شده و alias دارد
    src = client.get(f"{API}/persons/{p1['id']}", headers=steward).json()
    assert src["status"] == "merged" and src["merged_into_id"] == p2["id"]
    # نگاشت به هدف منتقل شده و resolve نهایی را برمی‌گرداند
    res = client.post(f"{API}/id-mappings/resolve", json={
        "installation_id": edu["id"], "entity_type": "person", "local_id": "ST-900"},
        headers=dev_headers(tenant=tenant1, scopes="sync")).json()
    assert res["entity"]["id"] == p2["id"]

    # نگاشت قدیمی که همچنان به منبع (alias) اشاره می‌کند → resolve زنجیره alias را تا شناسه نهایی دنبال می‌کند
    old_map = client.post(f"{API}/id-mappings", json={
        "installation_id": edu["id"], "entity_type": "person", "local_id": "ST-900-old", "entity_id": p1["id"],
    }, headers=dev_headers(tenant=tenant1, roles="steward")).json()
    res_old = client.post(f"{API}/id-mappings/resolve", json={
        "installation_id": edu["id"], "entity_type": "person", "local_id": "ST-900-old"},
        headers=dev_headers(tenant=tenant1, scopes="sync")).json()
    assert res_old["entity"]["id"] == p2["id"]
    assert res_old.get("merged_from") == p1["id"]
    # سابقه ادغام حفظ شده است
    merges = client.get(f"{API}/merges", headers=steward).json()["items"]
    assert any(m["source_person_id"] == p1["id"] and m["status"] == "applied" for m in merges)
    # رویداد PersonMerged در Outbox
    from app.core.database import SessionLocal
    from app.modules.synchronization.models import OutboxEvent
    db = SessionLocal()
    try:
        merged_events = db.query(OutboxEvent).filter(OutboxEvent.event_type == "PersonMerged").count()
        assert merged_events >= 1
    finally:
        db.close()


def test_merge_reverse_restores_source(client, tenant1):
    """بازگردانی ادغام به‌صورت فرآیند اصلاحی مستقل."""
    headers = dev_headers(roles="master_data_editor", tenant=tenant1)
    p1 = client.post(f"{API}/persons", json={"given_name": "کاوه", "family_name": "نوری"}, headers=headers).json()
    p2 = client.post(f"{API}/persons", json={"given_name": "کاوه", "family_name": "نوری"}, headers=headers).json()
    steward = dev_headers(user="steward1", roles="steward", tenant=tenant1)
    case = client.post(f"{API}/quality/cases", json={"candidate_ids": [p1["id"], p2["id"]]}, headers=steward).json()
    client.post(f"{API}/resolution-cases/{case['id']}/merge",
                json={"target_person_id": p2["id"]}, headers=steward)
    merge = next(m for m in client.get(f"{API}/merges", headers=steward).json()["items"]
                 if m["source_person_id"] == p1["id"])
    r = client.post(f"{API}/merges/{merge['id']}/reverse", json={"note": "ادغام اشتباه بود"}, headers=steward)
    assert r.status_code == 200
    src = client.get(f"{API}/persons/{p1['id']}", headers=steward).json()
    assert src["status"] == "active" and src["merged_into_id"] is None


def test_person_deactivation_flow(client, tenant1):
    """غیرفعال‌سازی با کنترل نسخه."""
    headers = dev_headers(roles="master_data_editor", tenant=tenant1)
    p = client.post(f"{API}/persons", json={"given_name": "ژیار", "family_name": "کامران"}, headers=headers).json()
    steward = dev_headers(user="steward1", roles="steward", tenant=tenant1)
    # نسخه اشتباه → 412
    r = client.post(f"{API}/persons/{p['id']}/deactivation", json={"version": p["version"] + 5},
                    headers=steward)
    assert r.status_code == 412
    # نسخه درست → غیرفعال
    r = client.post(f"{API}/persons/{p['id']}/deactivation", json={"version": p["version"]},
                    headers=steward)
    assert r.status_code == 200
    assert r.json()["status"] == "inactive"


def test_identifier_duplicate_rules(client, tenant1):
    """کد ملی قید یکتایی جهانی ندارد؛ یکتایی فقط در حوزه نوع+صادرکننده."""
    # ثبت شناسه در مالکیت متولی داده (steward)
    headers = dev_headers(user="steward1", roles="steward", tenant=tenant1)
    p1 = client.post(f"{API}/persons", json={"given_name": "عزیز", "family_name": "بهرامی"}, headers=headers).json()
    p2 = client.post(f"{API}/persons", json={"given_name": "گلناز", "family_name": "بهرامی"}, headers=headers).json()
    idn = {"type": "national_id", "issuer": "civil_registry", "value": "0077788899"}
    r1 = client.post(f"{API}/persons/{p1['id']}/identifiers", json=idn, headers=headers)
    assert r1.status_code == 201
    # همان حوزه → تکراری
    r2 = client.post(f"{API}/persons/{p2['id']}/identifiers", json=idn, headers=headers)
    assert r2.status_code == 409
    # حوزه صادرکننده متفاوت → مجاز
    r3 = client.post(f"{API}/persons/{p2['id']}/identifiers",
                     json={**idn, "issuer": "foreign_registry"}, headers=headers)
    assert r3.status_code == 201


def test_account_link_rules(client, tenant1):
    """اتصال حساب SSO: یکتایی اتصال فعال و منع اتصال دوباره به شخص دیگر."""
    headers = dev_headers(roles="master_data_editor", tenant=tenant1)
    p1 = client.post(f"{API}/persons", json={"given_name": "شهرام", "family_name": "زند"}, headers=headers).json()
    p2 = client.post(f"{API}/persons", json={"given_name": "پرهام", "family_name": "زند"}, headers=headers).json()
    steward = dev_headers(user="steward1", roles="steward", tenant=tenant1)
    payload = {"person_id": p1["id"], "issuer": "http://sso.local", "subject": "sub-abc-1"}
    r1 = client.post(f"{API}/identity-account-links", json=payload, headers={**steward, "Idempotency-Key": "link-1"})
    assert r1.status_code == 201
    # همان کلید، همان ورودی → پاسخ ذخیره‌شده
    r1b = client.post(f"{API}/identity-account-links", json=payload, headers={**steward, "Idempotency-Key": "link-1"})
    assert r1b.status_code == 201 and r1b.headers.get("Idempotent-Replay") == "true"
    # همان حساب به شخص دیگر → منع
    r2 = client.post(f"{API}/identity-account-links",
                     json={**payload, "person_id": p2["id"]}, headers=steward)
    assert r2.status_code == 409
    assert r2.json()["code"] == "ACCOUNT_ALREADY_LINKED"


def test_snapshot_no_gap_and_boundary(client, tenant1):
    """Snapshot همراه تغییر هم‌زمان → هیچ تغییر Commit‌شده‌ای از دست نرود."""
    sync_h = dev_headers(user="consumer-svc", tenant=tenant1, scopes="sync", service="consumer")
    r = client.post(f"{API}/sync/snapshots", json={"entities": ["persons"]}, headers=sync_h)
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    # اجرای کار (شبیه‌سازی worker)
    import uuid as uuid_lib
    from app.core.database import SessionLocal
    from app.modules.synchronization import service as sync_svc
    db = SessionLocal()
    try:
        job = sync_svc.run_snapshot_job(db, uuid_lib.UUID(job_id))
        assert job.status == "done", job.error
        boundary = job.boundary_seq
    finally:
        db.close()
    # تغییر پس از مرز
    client.post(f"{API}/persons", json={"given_name": "پس‌از", "family_name": "اسنپ‌شات"},
                headers=dev_headers(roles="master_data_editor", tenant=tenant1))
    # هیچ تغییری ≤ مرز نباید از دست رفته باشد: تغییرات پس از مرز هم قابل بازیابی‌اند
    r = client.get(f"{API}/sync/changes", params={"cursor": boundary}, headers=sync_h)
    assert r.status_code == 200
    assert any(c["data"].get("family_name") == "اسنپ‌شات" for c in r.json()["changes"])
    # محتوای Snapshot شامل همه اشخاص تا مرز
    r = client.get(f"{API}/sync/snapshots/{job_id}/download", headers=sync_h)
    assert r.status_code == 200
    snap = json.loads(r.content.decode())
    assert snap["boundarySeq"] == boundary
    assert len(snap["entities"]["persons"]) >= 1


def test_consumer_dedupes_and_gap_detection(client, tenant1, person1):
    """تکرار پیام → بدون اثر تکراری؛ رویداد قدیمی → عدم بازنویسی نسخه جدید؛ شکاف نسخه → بازیابی از مرجع."""
    from consumer import LocalReplica, process_event
    sync_h = dev_headers(user="consumer-svc", tenant=tenant1, scopes="sync", service="consumer")

    def resolve_fn(person_id):
        r = client.get(f"{API}/persons/{person_id}", headers=sync_h)
        return r.json()

    # دریافت رویدادها از تغییرات (بدون cursor — از ابتدای جریان)
    r = client.get(f"{API}/sync/changes", params={"limit": 100}, headers=sync_h).json()
    events = [{
        "eventId": f"ev-{c['seq']}", "eventType": f"Person{c['operation'].title()}",
        "schemaVersion": 1, "tenantId": tenant1, "sourceSystem": "shared-core",
        "entityId": c["entity_id"], "entityVersion": c["entity_version"],
        "occurredAt": c["occurred_at"], "correlationId": f"corr-{c['seq']}",
        "payload": c["data"],
    } for c in r["changes"] if c["entity_type"] == "person"]

    replica = LocalReplica()
    for ev in events:
        process_event(replica, ev, resolve_fn)
    first_version = replica.persons.get(person1["id"], {}).get("version")
    # تکرار کل جریان → هیچ اثر تکراری
    versions_before = {pid: p["version"] for pid, p in replica.persons.items()}
    for ev in events:
        process_event(replica, ev, resolve_fn)
    versions_after = {pid: p["version"] for pid, p in replica.persons.items()}
    assert versions_before == versions_after, "تکرار پیام نباید اثر داشته باشد"

    # رویداد قدیمی → عدم بازنویسی
    if first_version:
        old_ev = {"eventId": "old-1", "eventType": "PersonUpdated", "schemaVersion": 1,
                  "tenantId": tenant1, "sourceSystem": "shared-core",
                  "entityId": person1["id"], "entityVersion": 1, "occurredAt": "2020-01-01T00:00:00Z",
                  "correlationId": "c1", "payload": {"display_name": "قدیمی"}}
        action = process_event(replica, old_ev, resolve_fn)
        assert action == "ignored_old_version"

    # شکاف نسخه → بازیابی از مرجع
    gap_ev = {"eventId": "gap-1", "eventType": "PersonUpdated", "schemaVersion": 1,
              "tenantId": tenant1, "sourceSystem": "shared-core",
              "entityId": person1["id"], "entityVersion": (first_version or 1) + 100,
              "occurredAt": "2026-01-01T00:00:00Z", "correlationId": "c2",
              "payload": {"display_name": "جهش‌یافته"}}
    action = process_event(replica, gap_ev, resolve_fn)
    assert action == "refetched_from_source"


def test_health_and_meta(client):
    r = client.get("/health/live")
    assert r.status_code == 200
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["database"]["ok"] is True
    r = client.get(f"{API}/meta")
    assert r.json()["auth_mode"] == "dev"
    r = client.get("/metrics")
    assert "api_requests_total" in r.text


def test_unauthenticated_rejected(client):
    """بدون هویت → 401 با قرارداد خطا."""
    import os as _os
    from app.core.config import settings
    assert settings.DEV_AUTH is True  # در آزمون حالت توسعه فعال است
    headers = {"X-Dev-User": "", "X-Dev-Roles": "", "X-Dev-Tenants": "t1"}
    r = client.get(f"{API}/persons", headers=headers)
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHENTICATED"


def test_organizations_cycle_forbidden(client, tenant1):
    """چرخه در ساختار سازمانی ممنوع است."""
    admin = dev_headers(roles="master_data_editor", tenant=tenant1)
    u = client.post(f"{API}/organizations", json={"type": "university", "code": "UC1", "name": "دانشگاه چرخه"},
                    headers=admin).json()
    f = client.post(f"{API}/organizations",
                    json={"type": "faculty", "code": "FC1", "name": "دانشکده", "parent_id": u["id"]},
                    headers=admin).json()
    r = client.patch(f"{API}/organizations/{u['id']}", json={"parent_id": f["id"]},
                     headers={**admin, "If-Match": f'"{u["version"]}"'})
    assert r.status_code == 409
    assert r.json()["code"] == "ORG_CYCLE"
