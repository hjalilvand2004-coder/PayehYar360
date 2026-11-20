"""مدل سیاست مالکیت داده (FR-07)."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin


class OwnershipPolicy(Base, IdMixin, TimestampMixin):
    """مالکیت در سطح (entity_type, field_group).

    owner_type: role (نقش منطقی) | service (شناسه سرویس/نصب) | installation
    owner_code: کد نقش یا کد سرویس/نصب
    """
    __tablename__ = "ownership_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "owner_installation_id"],
            ["system_installations.tenant_id", "system_installations.id"],
            name="fk_ownership_owner_installation_composite",
        ),
        UniqueConstraint("tenant_id", "entity_type", "field_group", name="uq_ownership_entity_group"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)  # person, organization, reference_set
    field_group: Mapped[str] = mapped_column(String(60), nullable=False)  # general, identifiers, contacts, status
    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_code: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_installation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
