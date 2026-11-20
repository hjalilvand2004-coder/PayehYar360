"""دسترسی داده ماژول اشخاص."""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.persons.models import Person, PersonContact, PersonIdentifier
from app.modules.synchronization.models import ChangeLog


def get_person(db: Session, tenant_id, person_id) -> Person | None:
    # پذیرش رشته UUID نیز برای سادگی فراخوانی‌های داخلی
    if isinstance(person_id, str):
        person_id = uuid.UUID(person_id)
    return db.execute(
        select(Person).where(Person.tenant_id == tenant_id, Person.id == person_id)
    ).scalar_one_or_none()


def search_by_identifier_hash(db: Session, tenant_id, itype: str, value_hash: str) -> Person | None:
    row = db.execute(
        select(Person)
        .join(PersonIdentifier, (PersonIdentifier.person_id == Person.id) & (PersonIdentifier.tenant_id == Person.tenant_id))
        .where(
            Person.tenant_id == tenant_id,
            PersonIdentifier.type == itype,
            PersonIdentifier.value_hash == value_hash,
            PersonIdentifier.status == "active",
        )
        .limit(1)
    ).scalar_one_or_none()
    return row


def list_persons(db: Session, tenant_id, q: str | None, status: str | None,
                 limit: int, offset: int) -> tuple[list[Person], int]:
    stmt = select(Person).where(Person.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(Person.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Person.display_name.ilike(like),
            Person.given_name.ilike(like),
            Person.family_name.ilike(like),
        ))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = db.execute(stmt.order_by(Person.family_name, Person.given_name).limit(limit).offset(offset)).scalars().all()
    return list(items), int(total)


def list_identifiers(db: Session, tenant_id, person_id) -> list[PersonIdentifier]:
    return list(db.execute(
        select(PersonIdentifier).where(
            PersonIdentifier.tenant_id == tenant_id, PersonIdentifier.person_id == person_id
        ).order_by(PersonIdentifier.created_at)
    ).scalars().all())


def list_contacts(db: Session, tenant_id, person_id) -> list[PersonContact]:
    return list(db.execute(
        select(PersonContact).where(
            PersonContact.tenant_id == tenant_id, PersonContact.person_id == person_id
        ).order_by(PersonContact.created_at)
    ).scalars().all())


def list_person_history(db: Session, tenant_id, person_id, limit: int = 100) -> list[ChangeLog]:
    return list(db.execute(
        select(ChangeLog).where(
            ChangeLog.tenant_id == tenant_id,
            ChangeLog.entity_type == "person",
            ChangeLog.entity_id == str(person_id),
        ).order_by(ChangeLog.seq.desc()).limit(limit)
    ).scalars().all())
