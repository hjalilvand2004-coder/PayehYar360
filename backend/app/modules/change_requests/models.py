"""مدل درخواست اصلاح داده (FR-09) — مسیر اصلاح برای غیرمالکِ داده."""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin

JSON_V = JSON().with_variant(JSONB(), "postgresql")


class ChangeRequest(Base, IdMixin, TimestampMixin):
    __tablename__ = "change_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)   # person, ...
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    proposed_changes: Mapped[dict] = mapped_column(JSON_V, nullable=False)  # {"field": "مقدار پیشنهادی"}
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(120), nullable=False)
    requested_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open|approved|rejected|cancelled
    decided_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_version: Mapped[int | None] = mapped_column(nullable=True)  # نسخه پس از اعمال
