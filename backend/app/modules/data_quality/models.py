"""مدل‌های کیفیت داده: پرونده تکرار و سابقه ادغام (FR-13)."""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin

JSON_V = JSON().with_variant(JSONB(), "postgresql")


class ResolutionCase(Base, IdMixin, TimestampMixin):
    """پرونده بررسی تکرار: نامزدها، شواهد و تصمیم انسانی."""
    __tablename__ = "resolution_cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    candidate_ids: Mapped[list] = mapped_column(JSON_V, nullable=False)   # شناسه نامزدهای تکرار
    evidence: Mapped[dict] = mapped_column(JSON_V, nullable=False)        # منشأ و وضعیت تأیید شواهد
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open|decided|cancelled
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)  # {"merge_into": uuid, "note": ...}
    merge_record_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class MergeRecord(Base, IdMixin, TimestampMixin):
    """سابقه ادغام: شناسه قبلی، شناسه نهایی، تصمیم‌گیر و بازگردانی (بخش ۱۲)."""
    __tablename__ = "merge_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_person_id: Mapped[uuid.UUID] = mapped_column(nullable=False)  # شناسه قبلی (ادغام‌شده)
    target_person_id: Mapped[uuid.UUID] = mapped_column(nullable=False)  # شناسه نهایی
    decided_by: Mapped[str] = mapped_column(String(120), nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="applied", nullable=False)  # applied|reversed
    reversed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reversed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    alias_snapshot: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)  # اطلاعات شناسه قبلی برای alias
