"""مدل ممیزی — فقط افزودن؛ هیچ مسیر ویرایش/حذفی برای این جدول وجود ندارد (بخش ۱۴.۳)."""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin

JSON_V = JSON().with_variant(JSONB(), "postgresql")


class AuditLog(Base, IdMixin, TimestampMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_entity", "tenant_id", "entity_type", "entity_id"),
        Index("ix_audit_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)  # user|service
    actor_id: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor_roles: Mapped[list | None] = mapped_column(JSON_V, nullable=True)
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    before: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON متنی حفاظت‌شده
    after: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(60), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
