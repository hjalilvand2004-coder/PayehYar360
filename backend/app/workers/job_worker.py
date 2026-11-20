"""Worker کارهای زمان‌بندی: پردازش Snapshot و انقضای آن‌ها."""
from __future__ import annotations

import logging
import threading
from datetime import datetime

from sqlalchemy import select

from app.common.db import utcnow
from app.core.config import settings
from app.core.database import SessionLocal
from app.modules.synchronization import service as sync_svc
from app.modules.synchronization.models import SnapshotJob

log = logging.getLogger("core.jobs")

_stop = threading.Event()


def stop() -> None:
    _stop.set()


def _expire_old_jobs(db) -> None:
    now = utcnow()
    rows = list(db.execute(select(SnapshotJob).where(SnapshotJob.status == "done")).scalars().all())
    for job in rows:
        try:
            if job.expires_at and datetime.fromisoformat(str(job.expires_at)) < now:
                job.status = "expired"
        except ValueError:
            continue
    db.commit()


def run_loop(poll_seconds: float = 3.0) -> None:
    log.info("Job worker started")
    while not _stop.is_set():
        try:
            db = SessionLocal()
            try:
                queued = list(db.execute(
                    select(SnapshotJob).where(SnapshotJob.status == "queued").limit(5)
                ).scalars().all())
                for job in queued:
                    sync_svc.run_snapshot_job(db, job.id)
                _expire_old_jobs(db)
            finally:
                db.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("Job worker error: %s", exc)
        _stop.wait(poll_seconds)
    log.info("Job worker stopped")


def start() -> threading.Thread:
    _stop.clear()
    t = threading.Thread(target=run_loop, name="job-worker", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_loop()
