"""مدل ساختار سازمانی مشترک (FR-05)."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin


class Organization(Base, IdMixin, TimestampMixin):
    __tablename__ = "organizations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"], ["organizations.tenant_id", "organizations.id"],
            name="fk_organizations_parent_composite",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_organizations_tenant_id"),
        UniqueConstraint("tenant_id", "type", "code", name="uq_organizations_type_code"),
        Index("ix_organizations_tenant_parent", "tenant_id", "parent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    type: Mapped[str] = mapped_column(String(40), nullable=False)  # university, campus, faculty, department, group
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
