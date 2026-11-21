"""قرارداد ورودی/خروجی ماژول سازمان‌ها."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: uuid.UUID | None = None
    type: str = Field(min_length=3, max_length=40)
    code: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = 0


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_id: uuid.UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=60)  # تغییر کد با بررسی یکتایی
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sort_order: int | None = None
    status: str | None = None
