"""API ماژول دانشجویان — مسیرها نازک؛ منطق در service.

نکته ترتیب: مسیرهای ایستا (/stats، /sync، /ingest) پیش از /{student_id} ثبت می‌شوند.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.common.idempotency import execute_idempotent
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant, require_roles
from app.core.errors import AppError, forbidden, not_found
from app.core.security import Actor
from app.modules.integrations.models import Tenant
from app.modules.students import schemas as S, service as svc

router = APIRouter(prefix="/students", tags=["students"])


def _parse_if_match(if_match: str | None, body_version: int | None) -> int:
    if if_match:
        token = if_match.strip()
        if token.startswith("W/"):
            token = token[2:]
        token = token.strip('"')
        try:
            return int(token)
        except ValueError:
            raise AppError("INVALID_IF_MATCH", "هدر If-Match باید شماره نسخه باشد.", 400)
    if body_version is not None:
        return body_version
    raise AppError("VERSION_REQUIRED", "ارسال هدر If-Match با نسخه فعلی الزامی است.", 400)


class VersionIn(BaseModel):
    version: int | None = None


class IngestIn(BaseModel):
    items: list[dict] = Field(default_factory=list, max_length=1000)


# ------------------------------------------------ فهرست/آمار (مشاهده: همه نقش‌ها)

@router.get("")
def list_students(request: Request, q: str | None = None, degree_level: str | None = None,
                  university_code: str | None = None, city: str | None = None,
                  status: str | None = None, source: str | None = None,
                  limit: int = 25, offset: int = 0,
                  actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                  db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    return svc.list_students(db, tenant.id, q=q, degree_level=degree_level,
                             university_code=university_code, city=city, status=status,
                             source=source, limit=limit, offset=offset)


@router.get("/stats")
def student_stats(actor: Actor = Depends(get_actor), tenant: Tenant = Depends(get_tenant),
                  db: Session = Depends(get_db)):
    return svc.stats(db, tenant.id)


# ------------------------------------------------ همگام‌سازی دانشگاه هوشمند

@router.post("/sync")
def sync_students(request: Request,
                  actor: Actor = Depends(require_roles("steward", "integration_admin", "tenant_admin")),
                  tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    correlation_id = getattr(request.state, "correlation_id", None)
    report = svc.sync_from_smart_university(db, tenant.id, actor, request=request,
                                            correlation_id=correlation_id)
    db.commit()
    return report


def _ingest_tenant(request: Request, db: Session = Depends(get_db)) -> Tenant:
    """احراز سرویس‌به‌سرویس با کلید API — بدون توکن کاربر؛ مشتری از هدر X-Tenant-Code."""
    if not settings.STUDENTS_INGEST_KEY:
        raise AppError("INGEST_DISABLED",
                       "دریافت push دانشجو فعال نیست؛ متغیر STUDENTS_INGEST_KEY تنظیم نشده است.", 503)
    if (request.headers.get("x-api-key") or "") != settings.STUDENTS_INGEST_KEY:
        raise forbidden("INVALID_API_KEY", "کلید API نامعتبر است.")
    code = (request.headers.get("x-tenant-code") or "").strip().lower()
    if not code:
        raise AppError("TENANT_REQUIRED", "هدر X-Tenant-Code لازم است.", 400)
    tenant = db.query(Tenant).filter(Tenant.code == code).first()
    if tenant is None or tenant.status != "active":
        raise not_found("مشتری موردنظر یافت نشد یا غیرفعال است.")
    return tenant


@router.post("/ingest")
def ingest_students(payload: IngestIn, request: Request,
                    tenant: Tenant = Depends(_ingest_tenant), db: Session = Depends(get_db)):
    correlation_id = getattr(request.state, "correlation_id", None)
    # هویت سرویس مبدأ — ممیزی با برچسب سامانه مبدأ ثبت می‌شود
    from app.core.security import Actor
    service_actor = Actor(kind="service", subject="smart-university", name="فضایار۳۶۰ (دانشگاه هوشمند)",
                          tenant_codes=[tenant.code], scopes=set())
    report = svc.ingest_from_smart_university(db, tenant.id, service_actor, payload.items,
                                              request=request, correlation_id=correlation_id)
    db.commit()
    return report


# ------------------------------------------------ ثبت دستی و گردش

@router.post("", status_code=201)
def create_student(request: Request, payload: S.StudentCreate,
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
                   actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                   tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    correlation_id = getattr(request.state, "correlation_id", None)
    result = execute_idempotent(
        db, tenant.id, idempotency_key, actor, payload.model_dump(),
        lambda: (201, svc.create_student(db, tenant.id, actor, payload.model_dump(), request=request,
                                         correlation_id=correlation_id)),
    )
    db.commit()
    return Response(content=json.dumps(result.body, ensure_ascii=False),
                    status_code=result.status, media_type="application/json",
                    headers={"Idempotent-Replay": "true"} if result.replayed else None)


@router.get("/{student_id}")
def get_student_detail(student_id: uuid.UUID, actor: Actor = Depends(get_actor),
                       tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.student_detail(db, tenant.id, student_id)


@router.patch("/{student_id}")
def patch_student(student_id: uuid.UUID, payload: S.StudentUpdate,
                  if_match: str | None = Header(default=None, alias="If-Match"),
                  actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                  tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db),
                  request: Request = None):
    changes = payload.model_dump(exclude_none=True)
    expected = _parse_if_match(if_match, None)
    correlation_id = getattr(request.state, "correlation_id", None) if request else None
    result = svc.update_student(db, tenant.id, actor, student_id, changes, expected,
                                request=request, correlation_id=correlation_id)
    db.commit()
    return result


@router.post("/{student_id}/deactivation")
def deactivate_student(student_id: uuid.UUID, payload: VersionIn,
                       if_match: str | None = Header(default=None, alias="If-Match"),
                       reason: str | None = None,
                       actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                       tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db),
                       request: Request = None):
    expected = _parse_if_match(if_match, payload.version)
    result = svc.deactivate_student(db, tenant.id, actor, student_id, expected, reason, request=request)
    db.commit()
    return result
