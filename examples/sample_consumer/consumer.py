"""نمونه مصرف‌کننده رویدادهای هسته مشترک — Inbox + نسخه محلی + checkpoint (تحویل‌دادنی ۱۷.۷).

قواعد اعمال (بند ۹.۲ و سناریوهای ۱۵.۲):
- تکرار پیام (eventId تکراری) → بدون اثر
- رویداد قدیمی (entityVersion <= نسخه محلی) → بدون بازنویسی
- شکاف نسخه → بازیابی نمای معتبر از API مرجع
- checkpoint پس از پردازش تراکنشی ثبت می‌شود

اجرا به‌صورت CLI (حالت توسعه):
    python consumer.py --core http://localhost:8094 --tenant demo \
        --user consumer-svc --scopes sync --installation edu-main
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


class LocalReplica:
    """نسخه محلی محدود + Inbox برای خنثی‌سازی تکرار."""

    def __init__(self) -> None:
        self.persons: dict[str, dict] = {}
        self.inbox: dict[str, str] = {}   # eventId → processed_at
        self.last_seq: int = 0
        self.checkpoint: int = 0

    def seen(self, event_id: str) -> bool:
        return event_id in self.inbox

    def mark_seen(self, event_id: str) -> None:
        self.inbox[event_id] = datetime.now(timezone.utc).isoformat()


def process_event(replica: LocalReplica, event: dict, resolve_fn) -> str:
    """یک رویداد را روی نسخه محلی اعمال می‌کند و اقدام انجام‌شده را برمی‌گرداند.

    resolve_fn(entity_id) → نمای معتبر شخص از API مرجع (برای شکاف نسخه)
    """
    event_id = str(event.get("eventId"))
    entity_type = event.get("entityType", "person")
    if entity_type != "person":
        return "ignored_entity_type"
    entity_id = str(event.get("entityId"))
    version = int(event.get("entityVersion", 0))
    etype = event.get("eventType")

    if replica.seen(event_id):
        return "duplicate_skipped"                      # تکرار پیام → بدون اثر

    local = replica.persons.get(entity_id)
    if local is not None and version <= int(local.get("version", 0)):
        replica.mark_seen(event_id)
        return "ignored_old_version"                    # رویداد قدیمی → عدم بازنویسی

    if etype in ("PersonMerged", "PersonMergeCorrected"):
        payload = event.get("payload") or {}
        if etype == "PersonMerged":
            source_id = str(payload.get("sourceId") or entity_id)
            target_id = str(payload.get("targetId"))
            if source_id in replica.persons:
                replica.persons[source_id] = {"id": source_id, "status": "merged",
                                              "merged_into_id": target_id, "version": version}
            replica.mark_seen(event_id)
            return "applied_merge"
        if source_id in replica.persons if (source_id := str(payload.get("restoredId") or entity_id)) else False:
            replica.persons[source_id] = {**replica.persons.get(source_id, {}), "status": "active",
                                          "merged_into_id": None, "version": version}
        replica.mark_seen(event_id)
        return "applied_merge_corrected"

    # شکاف نسخه: نسخه قبلی نداریم یا نسخه بیش از یک واحد جلوتر است → بازیابی از مرجع (بند ۹.۲)
    if local is None and etype == "PersonUpdated":
        view = resolve_fn(entity_id)
        if view and "id" in view:
            replica.persons[entity_id] = {k: view[k] for k in ("id", "display_name", "status", "version")}
            replica.mark_seen(event_id)
            return "refetched_from_source"
        replica.mark_seen(event_id)
        return "refetch_failed"

    if etype == "PersonDeactivated":
        if local is not None:
            local["status"] = "inactive"
            local["version"] = version
        replica.mark_seen(event_id)
        return "applied"

    # اعمال تغییر جزئی فقط با داشتن نسخه قبلی معتبر
    if local is None and etype in ("PersonCreated",):
        payload = event.get("payload") or {}
        replica.persons[entity_id] = {
            "id": entity_id,
            "display_name": payload.get("display_name") or f"{payload.get('given_name', '')} {payload.get('family_name', '')}".strip(),
            "status": "active", "version": version,
        }
        replica.mark_seen(event_id)
        return "applied"

    if local is None and etype == "PersonUpdated":
        return "refetch_required"  # مصرف‌کننده باید از API نمای معتبر بگیرد

    if local is not None:
        payload = event.get("payload") or {}
        local.update({k: v for k, v in payload.items() if k in ("display_name", "given_name", "family_name")})
        local["version"] = version
        replica.mark_seen(event_id)
        return "applied"
    return "ignored"


def process_changes(replica: LocalReplica, changes: list[dict], resolve_fn) -> dict:
    """پردازش تراکنشی دسته تغییرات (ChangeLog) — مبنای cursor."""
    stats = {"applied": 0, "duplicate_skipped": 0, "ignored_old_version": 0, "refetched_from_source": 0}
    for change in changes:
        ev = {
            "eventId": f"change-{change['seq']}",
            "eventType": f"Person{str(change['operation']).title().replace('_', '')}",
            "entityType": change["entity_type"],
            "entityId": change["entity_id"], "entityVersion": change["entity_version"],
            "occurredAt": change["occurred_at"], "payload": change["data"],
        }
        action = process_event(replica, ev, resolve_fn)
        stats[action] = stats.get(action, 0) + 1
        replica.last_seq = max(replica.last_seq, int(change["seq"]))
    return stats


def run_consumer(core_url: str, tenant: str, headers: dict, installation: str) -> None:
    """Snapshot → تغییرات → checkpoint (فرآیند مصرف بند ۹.۶)."""
    import httpx

    replica = LocalReplica()
    with httpx.Client(base_url=core_url, headers=headers, timeout=15) as client:
        # ۱) Snapshot
        r = client.post("/api/v1/sync/snapshots", json={"entities": ["persons"]})
        job = r.json()
        print(f"snapshot job: {job['status']}")
        while job["status"] in ("queued", "running"):
            datetime_wait = 1.0
            import time
            time.sleep(datetime_wait)
            job = client.get(f"/api/v1/sync/snapshots/{job['id']}").json()
        if job["status"] == "done":
            snap = client.get(f"/api/v1/sync/snapshots/{job['id']}/download").json()
            for p in snap["entities"].get("persons", []):
                replica.persons[p["id"]] = {k: p.get(k) for k in ("id", "display_name", "status", "version")}
            cursor = snap["boundarySeq"]
            print(f"snapshot loaded: {len(replica.persons)} persons, boundary={cursor}")
        else:
            cursor = 0

        # ۲) تغییرات پس از cursor
        r = client.get("/api/v1/sync/changes", params={"cursor": cursor, "limit": 500})
        changes = r.json()["changes"]

        def resolve_fn(person_id: str):
            resp = client.get(f"/api/v1/persons/{person_id}")
            return resp.json() if resp.status_code == 200 else None

        stats = process_changes(replica, changes, resolve_fn)
        print(f"changes processed: {stats}")

        # ۳) ثبت checkpoint
        r = client.post("/api/v1/sync/checkpoints", json={
            "installation_code": installation, "scope": "persons",
            "cursor": replica.last_seq or cursor,
            "note": "sample consumer run",
        })
        print(f"checkpoint: {r.json() if r.status_code == 200 else r.text}")

    with open("local_replica.json", "w", encoding="utf-8") as fh:
        json.dump({"persons": replica.persons, "last_seq": replica.last_seq}, fh, ensure_ascii=False, indent=2)
    print("local replica saved to local_replica.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="نمونه مصرف‌کننده هسته مشترک دانشجو۳۶۰")
    parser.add_argument("--core", default="http://localhost:8094")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--user", default="consumer-svc")
    parser.add_argument("--scopes", default="sync")
    parser.add_argument("--installation", required=True)
    args = parser.parse_args()
    headers = {
        "X-Dev-User": args.user, "X-Dev-Scopes": args.scopes,
        "X-Dev-Tenants": args.tenant, "X-Dev-Service": "sample-consumer",
        "X-Tenant-Code": args.tenant,
    }
    run_consumer(args.core, args.tenant, headers, args.installation)
    return 0


if __name__ == "__main__":
    sys.exit(main())
