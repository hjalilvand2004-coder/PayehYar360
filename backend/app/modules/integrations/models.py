"""مدل‌های مشتری‌ها و نصب‌های سامانه‌ها (FR-15)."""
from __future__ import annotations

import uuid

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin


class Tenant(Base, IdMixin, TimestampMixin):
    __tablename__ = "tenants"

    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class SystemInstallation(Base, IdMixin, TimestampMixin):
    """نصب یک زیرسامانه متصل (منبع یا مصرف‌کننده)."""
    __tablename__ = "system_installations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "installation_code", name="uq_installation_code"),
        UniqueConstraint("tenant_id", "id", name="uq_system_installations_tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    system_code: Mapped[str] = mapped_column(String(60), nullable=False)      # edu, research, sso, ...
    installation_code: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), default="integrated", nullable=False)  # local | integrated
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    owner_scopes: Mapped[str | None] = mapped_column(String(300), nullable=True)  # owner:person,read:persons
    last_seen_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
