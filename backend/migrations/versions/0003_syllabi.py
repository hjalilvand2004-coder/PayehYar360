"""Migration 0003 — جداول سرفصل‌های مصوب دروس.

- md_course_syllabi       : سرفصل مصوب هر درس (از فایل‌های وزارت علوم یا درج دستی)
- md_course_syllabus_topics : سرفصل/ریز محتوای هر درس با ساعت نظری/عملی

Revision ID: 0003_syllabi
Revises: 0002_reference_item_attrs
Create Date: 2026-11-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_syllabi"
down_revision = "0002_reference_item_attrs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "md_course_syllabi",
        sa.Column("id", postgresql.UUID(as_uuid=True) if op.get_bind().dialect.name == "postgresql" else sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36) if op.get_bind().dialect.name != "postgresql" else postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_set", sa.String(30), nullable=False),
        sa.Column("source_file", sa.String(300), nullable=False),
        sa.Column("title_fa", sa.String(300), nullable=True),
        sa.Column("title_en", sa.String(300), nullable=False),
        sa.Column("course_code", sa.String(60), nullable=True),
        sa.Column("course_type", sa.String(120), nullable=True),
        sa.Column("unit_theory", sa.Integer(), nullable=True),
        sa.Column("unit_practice", sa.Integer(), nullable=True),
        sa.Column("hour_theory", sa.Integer(), nullable=True),
        sa.Column("hour_practice", sa.Integer(), nullable=True),
        sa.Column("prerequisites", sa.Text(), nullable=True),
        sa.Column("corequisites", sa.Text(), nullable=True),
        sa.Column("general_goal", sa.Text(), nullable=True),
        sa.Column("evaluation", sa.Text(), nullable=True),
        sa.Column("references", sa.Text(), nullable=True),
        sa.Column("has_text", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("source", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "source_set", "source_file", name="uq_md_syllabus_file"),
    )
    op.create_index("ix_md_syllabi_tenant", "md_course_syllabi", ["tenant_id"])
    op.create_index("ix_md_syllabi_set", "md_course_syllabi", ["source_set"])

    op.create_table(
        "md_course_syllabus_topics",
        sa.Column("id", sa.String(36) if op.get_bind().dialect.name != "postgresql" else postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("syllabus_id", sa.String(36) if op.get_bind().dialect.name != "postgresql" else postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("hours", sa.Integer(), nullable=True),
        sa.Column("hours_practice", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_syllabus_topics_syllabus", "md_course_syllabus_topics", ["syllabus_id", "seq"])


def downgrade() -> None:
    op.drop_table("md_course_syllabus_topics")
    op.drop_table("md_course_syllabi")
