"""قرارداد ورودی/خروجی ماژول اشخاص (Pydantic v2)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IdentifierIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=2, max_length=40, examples=["national_id"])
    issuer: str = Field(min_length=2, max_length=80, examples=["civil_registry"])
    value: str = Field(min_length=3, max_length=120)
    verification_status: str = "unverified"  # unverified|verified|rejected


class ContactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=2, max_length=40, examples=["email"])
    value: str = Field(min_length=3, max_length=200)


class PersonCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    given_name: str = Field(min_length=1, max_length=120)
    family_name: str = Field(min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=240)
    identifiers: list[IdentifierIn] = []
    contacts: list[ContactIn] = []


class PersonUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    given_name: str | None = Field(default=None, min_length=1, max_length=120)
    family_name: str | None = Field(default=None, min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def _at_least_one(self):
        if all(v is None for v in (self.given_name, self.family_name, self.display_name)):
            raise ValueError("حداقل یک فیلد برای اصلاح لازم است.")
        return self


class PersonOut(BaseModel):
    id: uuid.UUID
    given_name: str
    family_name: str
    display_name: str
    status: str
    version: int
    merged_into_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class IdentifierOut(BaseModel):
    id: uuid.UUID
    type: str
    issuer: str
    value_masked: str
    verification_status: str
    status: str
    created_at: datetime


class ContactOut(BaseModel):
    id: uuid.UUID
    type: str
    value: str
    verified_at: str | None = None
    status: str


class AccountLinkOut(BaseModel):
    id: uuid.UUID
    issuer: str
    subject: str
    account_label: str | None
    status: str
    linked_at: str | None


class MappingOut(BaseModel):
    id: uuid.UUID
    installation_id: uuid.UUID
    installation_code: str | None = None
    entity_type: str
    local_id: str
    entity_id: uuid.UUID
    status: str


class PersonDetailOut(PersonOut):
    identifiers: list[IdentifierOut] = []
    contacts: list[ContactOut] = []
    account_links: list[AccountLinkOut] = []
    mappings: list[MappingOut] = []


class PersonListOut(BaseModel):
    items: list[PersonOut]
    total: int
    limit: int
    offset: int


class IdentifierCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=2, max_length=40)
    issuer: str = Field(min_length=2, max_length=80)
    value: str = Field(min_length=3, max_length=120)
    verification_status: str = "unverified"


class IdentifierPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_status: str | None = None  # verified|rejected
    status: str | None = None               # active|revoked


class ContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=2, max_length=40)
    value: str = Field(min_length=3, max_length=200)


class ContactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str | None = None       # active|revoked
    verified: bool | None = None
