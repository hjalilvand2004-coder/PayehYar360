"""Migration 0002 — افزودن ستون attrs (JSON اختیاری) به reference_items.

برای ذخیره ویژگی‌های آیتم‌های مرجع (مثلاً واحد/سال/پیش‌نیاز درس‌های یکتای واردشده
از سامانه نظرسنجی دروس ۳۶۰).

Revision ID: 0002_reference_item_attrs
Revises: 0001_initial
Create Date: 2026-11-20
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_reference_item_attrs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reference_items", sa.Column("attrs", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("reference_items", "attrs")
