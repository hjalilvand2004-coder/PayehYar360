"""مدل فهرست‌های مرجع با نسخه‌بندی (FR-06)."""
from __future__ import annotations

import uuid

from sqlalchemy import Date, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin


class ReferenceSet(Base, IdMixin, TimestampMixin):
    __tablename__ = "reference_sets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_reference_sets_code"),
        UniqueConstraint("tenant_id", "id", name="uq_reference_sets_tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner_installation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class ReferenceItem(Base, IdMixin, TimestampMixin):
    __tablename__ = "reference_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "set_id"], ["reference_sets.tenant_id", "reference_sets.id"],
            name="fk_reference_items_set_composite", ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"], ["reference_items.tenant_id", "reference_items.id"],
            name="fk_reference_items_parent_composite",
        ),
        UniqueConstraint("tenant_id", "set_id", "code", name="uq_reference_items_set_code"),
        UniqueConstraint("tenant_id", "id", name="uq_reference_items_tenant_id"),
        Index("ix_reference_items_set", "tenant_id", "set_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    set_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|retired
    valid_from: Mapped[str | None] = mapped_column(Date, nullable=True)   # رشته تاریخ ذخیره می‌شود
    valid_to: Mapped[str | None] = mapped_column(Date, nullable=True)
