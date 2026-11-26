"""قرارداد ورودی/خروجی ماژول دانشجویان (Pydantic v2)."""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEGREE_PATTERN = "|".join([
    "kardani", "karshenasi", "karshenasi_arshad", "doktori_herfei", "doktori_takhassosi", "post_doktori",
])


class StudentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_number: str = Field(min_length=1, max_length=40, examples=["402113001"])
    national_id: str | None = Field(default=None, max_length=20, examples=["0012345678"])
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    father_name: str | None = Field(default=None, max_length=120)
    gender: str | None = Field(default=None, pattern="^(male|female)$")
    birth_date: str | None = Field(default=None, max_length=10, examples=["1382-05-12"])
    mobile: str = Field(min_length=1, max_length=20, examples=["09121234567"])
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=120)
    city: str = Field(min_length=1, max_length=80, examples=["تهران"])
    province: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=500)
    university_code: str | None = Field(default=None, max_length=40)
    university_name: str = Field(min_length=1, max_length=160, examples=["دانشگاه تهران"])
    major_code: str | None = Field(default=None, max_length=40)
    major_name: str = Field(min_length=1, max_length=160, examples=["مهندسی کامپیوتر"])
    degree_level: str = Field(pattern=f"^({DEGREE_PATTERN})$")
    entrance_year: int | None = Field(default=None, ge=1350, le=1500)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("mobile")
    @classmethod
    def _normalize_mobile(cls, v: str) -> str:
        # یک‌سازی شماره همراه: حذف فاصله/خط تیره؛ +98/0098 → 0
        m = re.sub(r"[\s\-()]", "", v)
        if m.startswith("+98"):
            m = "0" + m[3:]
        elif m.startswith("0098"):
            m = "0" + m[4:]
        if m.startswith("9") and len(m) == 10:
            m = "0" + m
        if not re.fullmatch(r"09\d{9}", m):
            raise ValueError("شماره همراه باید به‌صورت 11 رقمی 09xxxxxxxxx باشد.")
        return m

    @field_validator("national_id")
    @classmethod
    def _normalize_national_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        n = re.sub(r"\D", "", v)
        if len(n) != 10:
            raise ValueError("کد ملی باید 10 رقم باشد.")
        return n


class StudentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    father_name: str | None = Field(default=None, max_length=120)
    gender: str | None = Field(default=None, pattern="^(male|female)$")
    birth_date: str | None = Field(default=None, max_length=10)
    mobile: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=80)
    province: str | None = Field(default=None, max_length=80)
    address: str | None = Field(default=None, max_length=500)
    university_code: str | None = Field(default=None, max_length=40)
    university_name: str | None = Field(default=None, max_length=160)
    major_code: str | None = Field(default=None, max_length=40)
    major_name: str | None = Field(default=None, max_length=160)
    degree_level: str | None = Field(default=None, pattern=f"^({DEGREE_PATTERN})$")
    entrance_year: int | None = Field(default=None, ge=1350, le=1500)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("mobile")
    @classmethod
    def _normalize_mobile(cls, v: str | None) -> str | None:
        if v is None:
            return None
        m = re.sub(r"[\s\-()]", "", v)
        if m.startswith("+98"):
            m = "0" + m[3:]
        elif m.startswith("0098"):
            m = "0" + m[4:]
        if m.startswith("9") and len(m) == 10:
            m = "0" + m
        if not re.fullmatch(r"09\d{9}", m):
            raise ValueError("شماره همراه باید به‌صورت 11 رقمی 09xxxxxxxxx باشد.")
        return m

    @model_validator(mode="after")
    def _at_least_one(self):
        if all(v is None for k, v in self.model_dump().items() if k != "mobile"):
            raise ValueError("حداقل یک فیلد برای اصلاح لازم است.")
        return self


class StudentOut(BaseModel):
    id: uuid.UUID
    student_number: str
    national_id: str
    first_name: str
    last_name: str
    mobile: str
    city: str
    university_name: str
    major_name: str
    degree_level: str
    status: str
    source: str
    version: int
    updated_at: datetime


class StudentDetailOut(StudentOut):
    father_name: str
    gender: str
    birth_date: str
    phone: str
    email: str
    province: str
    address: str
    university_code: str
    major_code: str
    entrance_year: int | None
    notes: str
    ext_ref: str | None
    synced_at: str | None
    sync_batch: str | None
    created_at: datetime


class StudentListOut(BaseModel):
    items: list[StudentOut]
    total: int
    limit: int
    offset: int


class SyncReport(BaseModel):
    batch_id: str
    mode: str                      # pull | push
    remote_status: int | None = None
    total_remote: int = 0
    created: int = 0
    updated: int = 0
    skipped: list[dict] = []
    message: str = ""
    synced_at: str


class StatsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    by_degree: dict[str, int]
    by_source: dict[str, int]
    last_synced_at: str | None = None
