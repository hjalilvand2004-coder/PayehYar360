"""دسترسی داده ماژول دانشجویان."""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.students.models import Student


def get_student(db: Session, tenant_id, student_id) -> Student | None:
    if isinstance(student_id, str):
        student_id = uuid.UUID(student_id)
    return db.execute(
        select(Student).where(Student.tenant_id == tenant_id, Student.id == student_id)
    ).scalar_one_or_none()


def get_by_student_number(db: Session, tenant_id, student_number: str) -> Student | None:
    return db.execute(
        select(Student).where(Student.tenant_id == tenant_id, Student.student_number == student_number)
    ).scalar_one_or_none()


def get_by_national_id(db: Session, tenant_id, national_id: str) -> Student | None:
    if not national_id:
        return None
    return db.execute(
        select(Student).where(Student.tenant_id == tenant_id, Student.national_id == national_id)
    ).scalar_one_or_none()


def get_by_ext_ref(db: Session, tenant_id, ext_ref: str) -> Student | None:
    if not ext_ref:
        return None
    return db.execute(
        select(Student).where(Student.tenant_id == tenant_id, Student.ext_ref == ext_ref)
    ).scalar_one_or_none()


def list_students(db: Session, tenant_id, *, q: str | None, degree_level: str | None,
                  university_code: str | None, city: str | None, status: str | None,
                  source: str | None, limit: int, offset: int) -> tuple[list[Student], int]:
    stmt = select(Student).where(Student.tenant_id == tenant_id)
    if degree_level:
        stmt = stmt.where(Student.degree_level == degree_level)
    if university_code:
        stmt = stmt.where(Student.university_code == university_code)
    if city:
        stmt = stmt.where(Student.city.ilike(f"%{city.strip()}%"))
    if status:
        stmt = stmt.where(Student.status == status)
    if source:
        stmt = stmt.where(Student.source == source)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Student.student_number.ilike(like),
            Student.first_name.ilike(like),
            Student.last_name.ilike(like),
            Student.national_id.ilike(like),
            Student.mobile.ilike(like),
            Student.major_name.ilike(like),
            Student.university_name.ilike(like),
            Student.city.ilike(like),
        ))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = db.execute(
        stmt.order_by(Student.last_name, Student.first_name).limit(limit).offset(offset)
    ).scalars().all()
    return list(items), int(total)


def degree_distribution(db: Session, tenant_id) -> dict[str, int]:
    rows = db.execute(
        select(Student.degree_level, func.count())
        .where(Student.tenant_id == tenant_id)
        .group_by(Student.degree_level)
    ).all()
    return {d: int(c) for d, c in rows}


def status_distribution(db: Session, tenant_id) -> dict[str, int]:
    rows = db.execute(
        select(Student.status, func.count())
        .where(Student.tenant_id == tenant_id)
        .group_by(Student.status)
    ).all()
    return {s: int(c) for s, c in rows}


def source_distribution(db: Session, tenant_id) -> dict[str, int]:
    rows = db.execute(
        select(Student.source, func.count())
        .where(Student.tenant_id == tenant_id)
        .group_by(Student.source)
    ).all()
    return {s: int(c) for s, c in rows}


def last_synced_at(db: Session, tenant_id) -> str | None:
    row = db.execute(
        select(func.max(Student.synced_at)).where(
            Student.tenant_id == tenant_id, Student.source == "smart_university"
        )
    ).scalar_one_or_none()
    return row
