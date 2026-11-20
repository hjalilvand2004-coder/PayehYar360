"""مدل‌های اشخاص، شناسه‌ها و تماس‌ها (FR-01..FR-04).

- UUID شناسه اصلی است؛ کد ملی/ایمیل/شماره دانشجویی قید یکتایی جهانی ندارند.
- مقدار حساس رمزشده + شاخص HMAC برای جست‌وجوی دقیق نگه‌داری می‌شود.
- active_key برای اعمال یکتایی مشروط به وضعیت فعال (سازگار بین PostgreSQL و SQLite) استفاده می‌شود.
- کلیدهای مرکب (tenant_id, person_id) عبور ارجاع بین دو مشتری متفاوت را منع می‌کنند.
"""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKeyConstraint, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin

JSON_V = JSON().with_variant(JSONB(), "postgresql")


class Person(Base, IdMixin, TimestampMixin):
    __tablename__ = "persons"
    __table_args__ = (
        # برای کلیدهای مرکب فرزندان (منع ارتباط بین دو مشتری متفاوت)
        UniqueConstraint("tenant_id", "id", name="uq_persons_tenant_id"),
        Index("ix_persons_tenant_family", "tenant_id", "family_name"),
        Index("ix_persons_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    given_name: Mapped[str] = mapped_column(String(120), nullable=False)
    family_name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|inactive|merged
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deactivated_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class PersonIdentifier(Base, IdMixin, TimestampMixin):
    __tablename__ = "person_identifiers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["persons.tenant_id", "persons.id"],
            name="fk_person_identifiers_person_composite", ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "person_id", "id", name="uq_person_identifiers_tenant_row"),
        UniqueConstraint("tenant_id", "active_key", name="uq_person_identifiers_active_key"),
        Index("ix_person_identifiers_hash", "tenant_id", "type", "value_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)     # national_id, student_number, ...
    issuer: Mapped[str] = mapped_column(String(80), nullable=False)   # civil_registry, edu, sso, ...
    encrypted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    value_masked: Mapped[str] = mapped_column(String(120), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), default="unverified", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|revoked
    active_key: Mapped[str | None] = mapped_column(String(150), nullable=True)  # type:issuer:hash در وضعیت فعال
    valid_from: Mapped[str | None] = mapped_column(String(40), nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


class PersonContact(Base, IdMixin, TimestampMixin):
    __tablename__ = "person_contacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["persons.tenant_id", "persons.id"],
            name="fk_person_contacts_person_composite", ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "person_id", "id", name="uq_person_contacts_tenant_row"),
        Index("ix_person_contacts_hash", "tenant_id", "type", "value_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)  # email, mobile, phone
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_installation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
