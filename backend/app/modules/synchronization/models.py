"""مدل‌های همگام‌سازی: ChangeLog، شمارنده ترتیب، Outbox/Inbox، Snapshot، Checkpoint، Idempotency (FR-10..FR-12)."""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, BigInteger, ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin

JSON_V = JSON().with_variant(JSONB(), "postgresql")


class TenantChangeCounter(Base):
    """شمارنده ترتیب تغییر هر مشتری — با قفل ردیف تخصیص می‌یابد (بند ۹.۵)."""
    __tablename__ = "tenant_change_counters"

    tenant_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class ChangeLog(Base):
    """تاریخچه تغییرات با شماره ترتیبی — مبنای cursor و بازسازی بدون شکاف."""
    __tablename__ = "change_log"
    __table_args__ = (
        UniqueConstraint("tenant_id", "seq", name="uq_change_log_seq"),
        Index("ix_change_log_entity", "tenant_id", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_version: Mapped[int] = mapped_column(nullable=False)
    operation: Mapped[str] = mapped_column(String(30), nullable=False)  # create|update|deactivate|merge|merge_corrected|link|mapping
    changed_fields: Mapped[list | None] = mapped_column(JSON_V, nullable=True)
    data: Mapped[dict] = mapped_column(JSON_V, nullable=False)  # فقط داده‌های مجاز مشترک
    actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occurred_at: Mapped[str] = mapped_column(String(40), nullable=False)


class OutboxEvent(Base, IdMixin, TimestampMixin):
    """رویداد در انتظار انتشار — با داده در یک تراکنش Commit می‌شود (بند ۹.۴).

    انتشار تکراری ممکن است؛ خنثی‌سازی تکرار بر عهده Inbox مصرف‌کننده با eventId است.
    """
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_status", "status", "next_attempt_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)  # همان eventId رویداد
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_V, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending|published|failed
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    next_attempt_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class InboxEvent(Base, IdMixin, TimestampMixin):
    """رویدادهای دریافتیِ پردازش‌شده توسط هسته (خنثی‌سازی تکرار با eventId)."""
    __tablename__ = "inbox_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)  # eventId پیام
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    consumer: Mapped[str] = mapped_column(String(80), nullable=False)
    processed_at: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)


class SnapshotJob(Base, IdMixin, TimestampMixin):
    """کار تولید Snapshot — از نمای سازگار و مرز متناظر همان نما (بند ۹.۵)."""
    __tablename__ = "snapshot_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    requested_by_installation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scope: Mapped[dict] = mapped_column(JSON_V, nullable=False)  # {"entities": ["persons", ...]}
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    boundary_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    counts: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class SyncCheckpoint(Base, IdMixin, TimestampMixin):
    """اعلام نقطه پردازش مصرف‌کننده — مبنای پایش فاصله (FR-17)."""
    __tablename__ = "sync_checkpoints"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "installation_id"],
            ["system_installations.tenant_id", "system_installations.id"],
            name="fk_sync_checkpoint_installation_composite",
        ),
        UniqueConstraint("tenant_id", "installation_id", "scope", name="uq_sync_checkpoint_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    installation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    scope: Mapped[str] = mapped_column(String(60), default="persons", nullable=False)
    cursor_seq: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    acknowledged_at: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReconciliationJob(Base, IdMixin, TimestampMixin):
    """کار تطبیق دوره‌ای نصب مستقل (پایه)."""
    __tablename__ = "reconciliation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    installation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="done", nullable=False)
    report: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class IdempotencyRecord(Base, IdMixin, TimestampMixin):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_idempotency_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    key: Mapped[str] = mapped_column(String(150), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(nullable=False)
    response_body: Mapped[dict] = mapped_column(JSON_V, nullable=False)
