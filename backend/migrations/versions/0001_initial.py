"""نسخه اولیه طرح داده هسته مشترک — ایجاد همه جدول‌ها از مدل‌های مصوب.

این Migration اولیه، طرح داده را مستقیماً از MetaData مدل‌های SQLAlchemy می‌سازد
(منبع واحد حقیقت). Migrationهای بعدی باید تغییرات تدریجی و صریح داشته باشند.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-20
"""
from __future__ import annotations

from alembic import op

from app.db_models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
