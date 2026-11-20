"""ناشر RabbitMQ — Publisher Confirm، پیام persistent، Exchange از نوع Topic (بند ۹.۳).

قطعی Broker باعث از دست رفتن داده نمی‌شود؛ رویدادها در Outbox می‌مانند و بعداً منتشر می‌شوند.
Publisher Confirm فقط دریافت توسط Broker را تضمین می‌کند، نه پردازش نهایی مصرف‌کننده.
"""
from __future__ import annotations

import json
import logging
import threading
import time

from app.core.config import settings

log = logging.getLogger("core.messaging")

_state_lock = threading.Lock()
_state = {
    "connected": False,
    "detail": "publishing disabled (RABBITMQ_URL خالی)",
    "last_publish_at": None,
    "published_total": 0,
}

ROUTING_KEY_BY_EVENT = {
    # topic: tenant.<code>.entity.<event>
    "PersonCreated": "person.created",
    "PersonUpdated": "person.updated",
    "PersonDeactivated": "person.deactivated",
    "PersonMerged": "person.merged",
    "PersonMergeCorrected": "person.merge_corrected",
    "OrganizationUpdated": "organization.updated",
    "ReferenceItemUpdated": "reference_item.updated",
    "IdentityAccountLinked": "identity.linked",
    "IdentifierMappingUpdated": "identity.mapping_updated",
}


def state() -> dict:
    with _state_lock:
        return dict(_state)


def _set(connected: bool, detail: str):
    with _state_lock:
        _state["connected"] = connected
        _state["detail"] = detail


def publish_events(events: list[dict]) -> tuple[int, int]:
    """انتشار دسته رویداد؛ خروجی: (تعداد موفق، تعداد شکست)."""
    if not settings.RABBITMQ_URL or not events:
        return (0, len(events) if not settings.RABBITMQ_URL else 0)
    try:
        import pika
        import pika.exceptions
    except ImportError:  # pragma: no cover
        _set(False, "کتابخانه pika نصب نیست")
        return (0, len(events))

    routing_base = settings.RABBITMQ_EXCHANGE
    published = 0
    try:
        params = pika.URLParameters(settings.RABBITMQ_URL)
        connection = pika.BlockingConnection(params)
        channel = connection.channel()
        channel.confirm_delivery()
        channel.exchange_declare(exchange=routing_base, exchange_type="topic", durable=True)
        for event in events:
            key = ROUTING_KEY_BY_EVENT.get(event.get("eventType"), "misc")
            tenant_id = str(event.get("tenantId", ""))
            routing_key = f"tenant.{tenant_id}.{key}"
            body = json.dumps(event, ensure_ascii=False).encode()
            try:
                channel.basic_publish(
                    exchange=routing_base, routing_key=routing_key, body=body,
                    properties=pika.BasicProperties(
                        content_type="application/json", delivery_mode=2,  # persistent
                        message_id=event.get("eventId"), type=event.get("eventType"),
                    ),
                    mandatory=False,
                )
                published += 1
                with _state_lock:
                    _state["published_total"] += 1
                    _state["last_publish_at"] = time.time()
            except pika.exceptions.UnroutableError:
                # پیام بدون مسیر معتبر — به‌عنوان شکست ثبت می‌شود تا Worker دوباره تلاش کند
                log.warning("Unroutable event %s (%s)", event.get("eventId"), routing_key)
            except pika.exceptions.NackError:
                log.warning("Broker nacked event %s", event.get("eventId"))
        connection.close()
        _set(True, "connected")
        return (published, len(events) - published)
    except Exception as exc:  # noqa: BLE001
        _set(False, f"{type(exc).__name__}: {exc}")
        return (published, len(events) - published)
