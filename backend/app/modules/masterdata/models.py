"""مدل‌های اطلاعات پایه چندسامانه‌ای: اساتید، کلاس‌ها/سالن‌ها، کلاینت‌های سرویس و تاریخچه واکشی."""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, IdMixin, TimestampMixin

JSON_V = JSON().with_variant(JSONB(), "postgresql")


class Instructor(Base, IdMixin, TimestampMixin):
    """استاد به‌عنوان اطلاعات پایه مشترک — کد منبع اصلی حفظ می‌شود (darsyar360 یا درج دستی)."""
    __tablename__ = "md_instructors"
    __table_args__ = (UniqueConstraint("tenant_id", "source_code", name="uq_md_instructor_code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_code: Mapped[str] = mapped_column(String(60), nullable=False)      # کد اصلی در سامانه منبع
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    rank: Mapped[str | None] = mapped_column(String(80), nullable=True)       # مرتبه علمی
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|retired
    source: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)  # darsyar360|manual|...
    extra: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)


class Classroom(Base, IdMixin, TimestampMixin):
    """کلاس/سالن درسی — واکشی از سامانه برنامه‌ریزی درسی (8083) یا درج دستی."""
    __tablename__ = "md_classrooms"
    __table_args__ = (UniqueConstraint("tenant_id", "source_code", name="uq_md_classroom_code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_code: Mapped[str] = mapped_column(String(60), nullable=False)      # کد اصلی در سامانه منبع
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str | None] = mapped_column(String(60), nullable=True)       # کلاس|سالن|آزمایشگاه|...
    building: Mapped[str | None] = mapped_column(String(200), nullable=True)
    capacity: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)


class ServiceClient(Base, IdMixin, TimestampMixin):
    """سامانه مصرف‌کننده اطلاعات پایه — با کلید API؛ هر واکشی در FetchLog ثبت می‌شود."""
    __tablename__ = "md_service_clients"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_md_service_client_code"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)             # مثل edu، research، scheduler
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)     # sha256 کلید
    api_key_masked: Mapped[str] = mapped_column(String(40), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON_V, nullable=False, default=list)  # دامنه‌های مجاز؛ خالی = همه
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|revoked
    last_seen_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_seen_at_jalali: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class FetchLog(Base, IdMixin, TimestampMixin):
    """تاریخچه واکشی و بروزرسانی:
    - direction=out : یک سامانه دیگر از ما سرویس گرفت
    - direction=in  : ما از منبع خارجی (darsyar360 / scheduler / manual) همگام‌سازی کردیم
    زمان‌ها هم میلادی (UTC) و هم شمسی ذخیره می‌شوند تا مصرف‌کننده‌های دیگر بدون تبدیل بخوانند.
    """
    __tablename__ = "md_fetch_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)  # برای تلاش ناموفق با کلید نادرست None
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # in|out
    domain: Mapped[str] = mapped_column(String(60), nullable=False)
    client_code: Mapped[str | None] = mapped_column(String(60), nullable=True)  # سامانه مصرف‌کننده
    client_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    source: Mapped[str | None] = mapped_column(String(60), nullable=True)       # منبع همگام‌سازی
    endpoint: Mapped[str | None] = mapped_column(String(300), nullable=True)
    record_count: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="success", nullable=False)  # success|failed
    http_status: Mapped[int | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[str] = mapped_column(String(40), nullable=False)        # UTC ISO
    occurred_at_jalali: Mapped[str] = mapped_column(String(40), nullable=False)  # ۱۴۰۵/۰۹/۰۱ ۱۲:۳۴


class CourseSyllabus(Base, IdMixin, TimestampMixin):
    """سرفصل مصوب یک درس — از فایل‌های سرفصل وزارت علوم یا درج دستی.
    یکتایی بر (tenant, مجموعه, فایل منبع)؛ سایر سامانه‌ها از دامنه course-syllabi مصرف می‌کنند.
    """
    __tablename__ = "md_course_syllabi"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_set", "source_file", name="uq_md_syllabus_file"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    source_set: Mapped[str] = mapped_column(String(30), nullable=False)       # 1394|CE403|NP1400
    source_file: Mapped[str] = mapped_column(String(300), nullable=False)     # نام فایل منبع
    title_fa: Mapped[str | None] = mapped_column(String(300), nullable=True)
    title_en: Mapped[str] = mapped_column(String(300), nullable=False)
    course_code: Mapped[str | None] = mapped_column(String(60), nullable=True)   # مثل CSE-313 یا 28-3
    course_type: Mapped[str | None] = mapped_column(String(120), nullable=True)  # نظری/عملی/اختیاری…
    unit_theory: Mapped[int | None] = mapped_column(nullable=True)
    unit_practice: Mapped[int | None] = mapped_column(nullable=True)
    hour_theory: Mapped[int | None] = mapped_column(nullable=True)
    hour_practice: Mapped[int | None] = mapped_column(nullable=True)
    prerequisites: Mapped[str | None] = mapped_column(Text, nullable=True)
    corequisites: Mapped[str | None] = mapped_column(Text, nullable=True)
    general_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation: Mapped[str | None] = mapped_column(Text, nullable=True)
    references: Mapped[str | None] = mapped_column(Text, nullable=True)          # منابع علمی
    has_text: Mapped[bool] = mapped_column(default=True, nullable=False)         # False = اسکن (نیازمند OCR)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)            # متن کامل استخراج‌شده
    # زنجیره درس: سرفصل متعلق به یک «درس تفکیکی» است (درس یکتا از طریق آن قابل دستیابی است)
    split_course_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


class CourseSyllabusTopic(Base, IdMixin, TimestampMixin):
    """سرفصل/ریز محتوای یک درس — ترتیب حفظ می‌شود؛ ساعت نظری/عملی در صورت وجود."""
    __tablename__ = "md_course_syllabus_topics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    syllabus_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    seq: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    hours: Mapped[int | None] = mapped_column(nullable=True)            # زمان نظری
    hours_practice: Mapped[int | None] = mapped_column(nullable=True)   # زمان عملی


class UniqueCourse(Base, IdMixin, TimestampMixin):
    """درس یکتا — رأس زنجیره درس؛ کد یکتا عیناً از سامانه درس‌یار۳۶۰ (بدون پیشوند).

    قاعده کسب‌وکار: هر درس یکتا ۱ تا ۳ «درس تفکیکی» دارد (تفکیک با سال یا مجموعه
    پیوسته/ناپیوسته) و هر درس تفکیکی سرفصل‌های مصوب خودش را دارد.
    """
    __tablename__ = "md_unique_courses"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_md_unique_course_code"),
        UniqueConstraint("tenant_id", "id", name="uq_md_unique_courses_tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)              # کد یکتا مثل 1044
    title_fa: Mapped[str] = mapped_column(String(300), nullable=False)
    title_en: Mapped[str | None] = mapped_column(String(300), nullable=True)
    section: Mapped[str | None] = mapped_column(String(80), nullable=True)     # بخش: پایه/اصلی/تخصصی/اختیاری/…
    unit_theory: Mapped[int | None] = mapped_column(nullable=True)
    unit_practice: Mapped[int | None] = mapped_column(nullable=True)
    capacity: Mapped[int | None] = mapped_column(nullable=True)                # ظرفیت برآوردی
    prerequisite: Mapped[str | None] = mapped_column(Text, nullable=True)      # پیش‌نیاز خام از منبع
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)  # darsyar360/manual
    extra: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)


class SplitCourse(Base, IdMixin, TimestampMixin):
    """درس تفکیکی — نمونه‌ی اجرایی یک درس یکتا؛ حلقه‌ی واسط زنجیره درس.

    یکتایی بر (درس یکتا + سال + مجموعه)؛ عنوان می‌تواند با عنوان درس یکتا
    کمی متفاوت باشد (مثل «ریاضیات گسسته» در ناپیوسته).
    """
    __tablename__ = "md_split_courses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "unique_course_id"], ["md_unique_courses.tenant_id", "md_unique_courses.id"],
            name="fk_md_split_course_unique", ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "unique_course_id", "year_label", "cohort_set",
                         name="uq_md_split_course_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    unique_course_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    code: Mapped[str | None] = mapped_column(String(60), nullable=True)        # کد ردیف در منبع
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    year_label: Mapped[str | None] = mapped_column(String(30), nullable=True)  # 1403 / 1394 / خالی
    cohort_set: Mapped[str | None] = mapped_column(String(30), nullable=True)  # پیوسته / ناپیوسته
    unit_theory: Mapped[int | None] = mapped_column(nullable=True)
    unit_practice: Mapped[int | None] = mapped_column(nullable=True)
    capacity: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(60), nullable=True)  # شناسه ردیف در منبع
    extra: Mapped[dict | None] = mapped_column(JSON_V, nullable=True)
