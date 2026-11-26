"""مدل ماژول دانشجویان (FR-05 — بخش ویژه ثبت دانشجویان).

- دانشجو موجودیت ثبتِ تحصیلیِ هسته است؛ داده از ثبت دستی یا همگام‌سازی دانشگاه هوشمند
  (فضایار۳۶۰) پر می‌شود.
- شماره دانشجویی در محدوده هر مشتری یکتاست؛ ext_ref (شناسه رکورد مبدأ) برای upsert سینک است.
- مقطع تحصیلی کد کانونی دارد (kardani..post_doktori) — برچسب فارسی در لایه نمایش.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin


class Student(Base, IdMixin, TimestampMixin):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_students_tenant_id"),
        UniqueConstraint("tenant_id", "student_number", name="uq_students_tenant_student_number"),
        Index("ix_students_tenant_degree", "tenant_id", "degree_level"),
        Index("ix_students_tenant_university", "tenant_id", "university_code"),
        Index("ix_students_tenant_status", "tenant_id", "status"),
        Index("ix_students_tenant_source", "tenant_id", "source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)

    # --- هویتی ---
    student_number: Mapped[str] = mapped_column(String(40), nullable=False)   # شماره دانشجویی
    national_id: Mapped[str] = mapped_column(String(20), default="", nullable=False)  # کد ملی
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    father_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    gender: Mapped[str] = mapped_column(String(10), default="", nullable=False)  # male|female
    birth_date: Mapped[str] = mapped_column(String(10), default="", nullable=False)  # YYYY-MM-DD

    # --- تماس و محل سکونت ---
    mobile: Mapped[str] = mapped_column(String(20), default="", nullable=False)  # 09xxxxxxxxx
    phone: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    city: Mapped[str] = mapped_column(String(80), default="", nullable=False)      # شهر محل سکونت
    province: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    address: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # --- وضعیت تحصیلی ---
    university_code: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    university_name: Mapped[str] = mapped_column(String(160), nullable=False)      # دانشگاه محل تحصیل
    major_code: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    major_name: Mapped[str] = mapped_column(String(160), nullable=False)           # رشته تحصیلی
    degree_level: Mapped[str] = mapped_column(String(30), nullable=False)          # مقطع (کد کانونی)
    entrance_year: Mapped[int | None] = mapped_column(Integer, nullable=True)      # سال ورود

    # --- گردش ---
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # active|graduated|withdrawn|suspended|inactive
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # --- منشأ داده ---
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)  # manual|smart_university
    ext_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)  # شناسه رکورد در سامانه مبدأ
    synced_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sync_batch: Mapped[str | None] = mapped_column(String(40), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)


DEGREE_LEVELS: dict[str, str] = {
    "kardani": "کاردانی",
    "karshenasi": "کارشناسی",
    "karshenasi_arshad": "کارشناسی ارشد",
    "doktori_herfei": "دکتری حرفه‌ای",
    "doktori_takhassosi": "دکتری تخصصی",
    "post_doktori": "پسادکتری",
}

# نام‌های رایج فارسی/انگلیسی مقاطع به کد کانونی — برای ثبت دستی و همگام‌سازی
DEGREE_ALIASES: dict[str, str] = {
    "kardani": "kardani", "کاردانی": "kardani", "associate": "kardani",
    "karshenasi": "karshenasi", "کارشناسی": "karshenasi", "کارشناسی پیوسته": "karshenasi",
    "bachelor": "karshenasi", "bsc": "karshenasi",
    "karshenasi_arshad": "karshenasi_arshad", "کارشناسی ارشد": "karshenasi_arshad",
    "ارشد": "karshenasi_arshad", "کارشناسی ناپیوسته": "karshenasi_arshad", "master": "karshenasi_arshad",
    "doktori_herfei": "doktori_herfei", "دکتری حرفه‌ای": "doktori_herfei", "دکترای حرفه‌ای": "doktori_herfei",
    "professional_doctorate": "doktori_herfei",
    "doktori_takhassosi": "doktori_takhassosi", "دکتری تخصصی": "doktori_takhassosi",
    "دکتری": "doktori_takhassosi", "phd": "doktori_takhassosi", "doctorate": "doktori_takhassosi",
    "post_doktori": "post_doktori", "پسادکتری": "post_doktori", "پست‌دکتری": "post_doktori",
    "postdoc": "post_doktori",
}

STUDENT_STATUSES: dict[str, str] = {
    "active": "فعال",
    "graduated": "فارغ‌التحصیل",
    "withdrawn": "انصراف‌داده",
    "suspended": "تعلیق‌شده",
    "inactive": "غیرفعال",
}

# وضعیت‌های سامانه مبدأ به وضعیت کانونی — برای همگام‌سازی
SOURCE_STATUS_ALIASES: dict[str, str] = {
    "active": "active", "فعال": "active", "studying": "active", "در حال تحصیل": "active",
    "graduated": "graduated", "فارغ‌التحصیل": "graduated", "فارغ التحصيل": "graduated",
    "withdrawn": "withdrawn", "انصراف": "withdrawn", "انصراف‌داده": "withdrawn",
    "suspended": "suspended", "تعلیق": "suspended", "تعلیق‌شده": "suspended", "احضار": "suspended",
    "inactive": "inactive", "غیرفعال": "inactive",
}
