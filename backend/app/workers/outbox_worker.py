"""Worker انتشار Outbox — حداقل یک‌بار تحویل؛ با lease ساده از پردازش هم‌زمان جلوگیری می‌کند."""
from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from sqlalchemy import select

from app.common.db import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.messaging import rabbitmq
from app.modules.synchronization.models import OutboxEvent

log = logging.getLogger("core.outbox")

_stop = threading.Event()


def stop() -> None:
    _stop.set()


def process_pending_batch() -> int:
    """یک دسته رویداد در انتظار را منتشر می‌کند؛ خروجی: تعداد منتشرشده."""
    now = utcnow().isoformat()
    db = SessionLocal()
    published = 0
    try:
        rows = list(db.execute(
            select(OutboxEvent)
            .where(OutboxEvent.status == "pending")
            .where((OutboxEvent.next_attempt_at.is_(None)) | (OutboxEvent.next_attempt_at <= now))
            .order_by(OutboxEvent.created_at)
            .limit(settings.OUTBOX_BATCH_SIZE)
        ).scalars().all())
        if not rows:
            return 0
        results = rabbitmq.publish_events([r.payload for r in rows])
        ok_count, fail_count = results
        # publish_events رویدادها را به ترتیب می‌فرستد؛ موفق‌ها را published می‌کنیم
        for row in rows[:ok_count]:
            row.status = "published"
            row.published_at = utcnow().isoformat()
            row.attempts += 1
            row.last_error = None
            published += 1
        for row in rows[ok_count:]:
            row.attempts += 1
            if settings.RABBITMQ_URL and row.attempts >= settings.OUTBOX_MAX_ATTEMPTS:
                row.status = "failed"  # برای بررسی عملیاتی؛ دستی بازنشانی می‌شود
            delay = min(300.0, settings.OUTBOX_RETRY_BASE_SECONDS * (2 ** min(row.attempts, 8)))
            row.next_attempt_at = (utcnow() + timedelta(seconds=delay)).isoformat()
            row.last_error = rabbitmq.state()["detail"]
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    finally:
        db.close()
    return published


def run_loop(poll_seconds: float | None = None) -> None:
    interval = poll_seconds or settings.OUTBOX_POLL_SECONDS
    log.info("Outbox worker started (interval=%.1fs, rabbitmq=%s)", interval, bool(settings.RABBITMQ_URL))
    while not _stop.is_set():
        try:
            process_pending_batch()
        except Exception as exc:  # noqa: BLE001
            log.warning("Outbox worker error: %s", exc)
        _stop.wait(interval)
    log.info("Outbox worker stopped")


def start() -> threading.Thread:
    _stop.clear()
    t = threading.Thread(target=run_loop, name="outbox-worker", daemon=True)
    t.start()
    return t


if __name__ == "__main__":  # اجرای مستقل: python -m app.workers.outbox_worker
    logging.basicConfig(level=logging.INFO)
    run_loop()
