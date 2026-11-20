"""مدل‌های هویت: اتصال حساب SSO، نگاشت شناسه محلی و ثبت موجودیت‌های مرجع (FR-03, FR-04)."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin


class IdentityAccountLink(Base, IdMixin, TimestampMixin):
    """نگاشت حساب SSO (issuer+subject) به شخص — بر اساس ایمیل مطلقاً انجام نمی‌شود."""
    __tablename__ = "identity_account_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["persons.tenant_id", "persons.id"],
            name="fk_identity_links_person_composite",
        ),
        # یکتایی فقط برای اتصال فعال (active_key = subject؛ هنگام قطع NULL می‌شود)
        UniqueConstraint("tenant_id", "issuer", "active_key", name="uq_identity_links_active"),
        Index("ix_identity_links_person", "tenant_id", "person_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False)   # issuer SSO
    subject: Mapped[str] = mapped_column(String(200), nullable=False)  # sub کاربر در SSO
    account_label: Mapped[str | None] = mapped_column(String(200), nullable=True)  # نام نمایشی/username برای UI
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|revoked
    active_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    linked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    linked_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class EntityRegistry(Base, IdMixin, TimestampMixin):
    """ثبت موجودیت‌های تخصصیِ مالکیت سایر سامانه‌ها (درس، پروژه، ...) — فقط شناسه و مرجع؛ مشخصات تخصصی ذخیره نمی‌شود."""
    __tablename__ = "entity_registry"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "authority_installation_id"],
            ["system_installations.tenant_id", "system_installations.id"],
            name="fk_entity_registry_authority_composite",
        ),
        UniqueConstraint("tenant_id", "entity_type", "authority_installation_id", "local_key",
                         name="uq_entity_registry_local"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)  # course, project, thesis, ...
    authority_installation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    local_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)  # معرفی خواندنی
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)


class ExternalIdMapping(Base, IdMixin, TimestampMixin):
    """نگاشت شناسه محلی زیرسامانه‌ها به شناسه مشترک هسته (FR-03)."""
    __tablename__ = "external_id_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "installation_id"], ["system_installations.tenant_id", "system_installations.id"],
            name="fk_id_mappings_installation_composite",
        ),
        UniqueConstraint("tenant_id", "installation_id", "entity_type", "local_id",
                         name="uq_id_mappings_local"),
        Index("ix_id_mappings_entity", "tenant_id", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    installation_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)  # person, organization, ...
    local_id: Mapped[str] = mapped_column(String(150), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(nullable=False)  # شناسه مشترک در هسته
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
