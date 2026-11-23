"""API اطلاعات پایه چندسامانه‌ای — مدیریت + سرویس‌دهی عمومی به سایر سامانه‌ها با کلید API."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant, require_roles
from app.core.errors import unauthorized
from app.core.security import Actor
from app.modules.masterdata import service as svc
from app.modules.masterdata.models import ServiceClient
from app.modules.integrations.models import Tenant

router = APIRouter(tags=["masterdata"])

# ---------- مدل‌های ورودی ----------


class ImportItems(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[dict] = Field(min_length=1)
    source: str = "manual"


class ServiceClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=60)
    title: str | None = None
    scopes: list[str] = Field(default_factory=list)  # خالی = همه دامنه‌ها
    note: str | None = None


# ---------- مسیرهای مدیریتی (نقش steward/admin) ----------


@router.get("/masterdata/catalog")
def catalog(actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
            tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.catalog(db, tenant.id)


@router.get("/masterdata/instructors")
def list_instructors(search: str | None = None, limit: int = 500,
                     actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
                     tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_instructors(db, tenant.id, search, limit)}


@router.get("/masterdata/classrooms")
def list_classrooms(search: str | None = None, limit: int = 500,
                    actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
                    tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_classrooms(db, tenant.id, search, limit)}


@router.post("/masterdata/import/instructors", status_code=201)
def import_instructors(payload: ImportItems, request: Request,
                       actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                       tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.import_instructors(db, tenant.id, actor, payload.items, payload.source)
    db.commit()
    return out


@router.post("/masterdata/import/classrooms", status_code=201)
def import_classrooms(payload: ImportItems, request: Request,
                      actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                      tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.import_classrooms(db, tenant.id, actor, payload.items, payload.source)
    db.commit()
    return out


# ---------- سرفصل‌های مصوب دروس ----------


@router.get("/masterdata/syllabi-stats")
def syllabi_stats(actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
                  tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.syllabi_stats(db, tenant.id)


@router.get("/masterdata/syllabi")
def list_syllabi(search: str | None = None, source_set: str | None = None,
                 split_course_id: str | None = None, limit: int = 500,
                 actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
                 tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_syllabi(db, tenant.id, search, source_set, split_course_id, limit)}


@router.get("/masterdata/syllabi/{syllabus_id}")
def get_syllabus(syllabus_id: uuid.UUID,
                 actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
                 tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.get_syllabus(db, tenant.id, syllabus_id)


@router.post("/masterdata/import/syllabi", status_code=201)
def import_syllabi(payload: ImportItems, request: Request,
                   actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                   tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.import_syllabi(db, tenant.id, actor, payload.items, payload.source)
    db.commit()
    return out


@router.delete("/masterdata/syllabi/set/{source_set}")
def delete_syllabus_set(source_set: str, request: Request,
                        actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                        tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.delete_syllabus_set(db, tenant.id, actor, source_set)
    db.commit()
    return out


class SyllabusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title_fa: str | None = None
    title_en: str | None = None
    course_code: str | None = None
    course_type: str | None = None
    unit_theory: int | None = None
    unit_practice: int | None = None
    hour_theory: int | None = None
    hour_practice: int | None = None
    prerequisites: str | None = None
    corequisites: str | None = None
    general_goal: str | None = None
    evaluation: str | None = None
    references: str | None = None
    topics: list[dict] | None = None
    split_course_id: str | None = None


@router.patch("/masterdata/syllabi/{syllabus_id}")
def update_syllabus(syllabus_id: uuid.UUID, payload: SyllabusUpdate, request: Request,
                    actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                    tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    out = svc.update_syllabus(db, tenant.id, actor, syllabus_id, data, request=request)
    db.commit()
    return out


# ---------- زنجیره درس: درس یکتا ← درس تفکیکی ← سرفصل مصوب ----------
# قاعده کسب‌وکار: هر درس یکتا ۱ تا ۳ درس تفکیکی دارد (تفکیک با سال یا مجموعه
# پیوسته/ناپیوسته) و هر درس تفکیکی سرفصل‌های مصوب خودش را دارد.

READ_ROLES = ("steward", "tenant_admin", "master_data_editor", "auditor")
WRITE_ROLES = ("steward", "tenant_admin", "master_data_editor")


class UniqueCourseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    title_fa: str
    title_en: str | None = None
    section: str | None = None
    unit_theory: int | None = None
    unit_practice: int | None = None
    capacity: int | None = None
    prerequisite: str | None = None
    status: str = "active"


class UniqueCourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = None
    title_fa: str | None = None
    title_en: str | None = None
    section: str | None = None
    unit_theory: int | None = None
    unit_practice: int | None = None
    capacity: int | None = None
    prerequisite: str | None = None
    status: str | None = None


class SplitCourseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unique_course_id: str
    code: str | None = None
    title: str | None = None
    year_label: str | None = None
    cohort_set: str | None = None
    unit_theory: int | None = None
    unit_practice: int | None = None
    capacity: int | None = None
    status: str = "active"


class SplitCourseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unique_course_id: str | None = None
    code: str | None = None
    title: str | None = None
    year_label: str | None = None
    cohort_set: str | None = None
    unit_theory: int | None = None
    unit_practice: int | None = None
    capacity: int | None = None
    status: str | None = None


class DarsyarRows(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[dict] = Field(min_length=1)


@router.get("/masterdata/unique-courses")
def list_unique_courses(search: str | None = None, section: str | None = None,
                        status: str | None = None, limit: int = 500, offset: int = 0,
                        actor: Actor = Depends(require_roles(*READ_ROLES)),
                        tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.list_unique_courses(db, tenant.id, search, section, status, limit, offset)


@router.post("/masterdata/unique-courses", status_code=201)
def create_unique_course(payload: UniqueCourseIn, request: Request,
                         actor: Actor = Depends(require_roles(*WRITE_ROLES)),
                         tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.create_unique_course(db, tenant.id, actor, payload.model_dump(), request=request)
    db.commit()
    return out


@router.get("/masterdata/unique-courses/{uc_id}")
def get_unique_course(uc_id: uuid.UUID,
                      actor: Actor = Depends(require_roles(*READ_ROLES)),
                      tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.get_unique_course(db, tenant.id, uc_id)


@router.patch("/masterdata/unique-courses/{uc_id}")
def update_unique_course(uc_id: uuid.UUID, payload: UniqueCourseUpdate, request: Request,
                         actor: Actor = Depends(require_roles(*WRITE_ROLES)),
                         tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.update_unique_course(db, tenant.id, actor, uc_id,
                                   payload.model_dump(exclude_unset=True), request=request)
    db.commit()
    return out


@router.delete("/masterdata/unique-courses/{uc_id}")
def delete_unique_course(uc_id: uuid.UUID, request: Request,
                         actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                         tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.delete_unique_course(db, tenant.id, actor, uc_id, request=request)
    db.commit()
    return out


@router.get("/masterdata/unique-courses/{uc_id}/split-courses")
def unique_course_splits(uc_id: uuid.UUID,
                         actor: Actor = Depends(require_roles(*READ_ROLES)),
                         tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.list_split_courses(db, tenant.id, unique_course_id=str(uc_id))


@router.get("/masterdata/split-courses")
def list_split_courses(unique_course_id: str | None = None, year: str | None = None,
                       cohort: str | None = None, search: str | None = None,
                       status: str | None = None, limit: int = 1000, offset: int = 0,
                       actor: Actor = Depends(require_roles(*READ_ROLES)),
                       tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.list_split_courses(db, tenant.id, unique_course_id, year, cohort, search, status, limit, offset)


@router.post("/masterdata/split-courses", status_code=201)
def create_split_course(payload: SplitCourseIn, request: Request,
                        actor: Actor = Depends(require_roles(*WRITE_ROLES)),
                        tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.create_split_course(db, tenant.id, actor, payload.model_dump(), request=request)
    db.commit()
    return out


@router.get("/masterdata/split-courses/{sc_id}")
def get_split_course(sc_id: uuid.UUID,
                     actor: Actor = Depends(require_roles(*READ_ROLES)),
                     tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.get_split_course(db, tenant.id, sc_id)


@router.patch("/masterdata/split-courses/{sc_id}")
def update_split_course(sc_id: uuid.UUID, payload: SplitCourseUpdate, request: Request,
                        actor: Actor = Depends(require_roles(*WRITE_ROLES)),
                        tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.update_split_course(db, tenant.id, actor, sc_id,
                                  payload.model_dump(exclude_unset=True), request=request)
    db.commit()
    return out


@router.delete("/masterdata/split-courses/{sc_id}")
def delete_split_course(sc_id: uuid.UUID, request: Request,
                        actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                        tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.delete_split_course(db, tenant.id, actor, sc_id, request=request)
    db.commit()
    return out


@router.get("/masterdata/split-courses/{sc_id}/syllabi")
def split_course_syllabi(sc_id: uuid.UUID,
                         actor: Actor = Depends(require_roles(*READ_ROLES)),
                         tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_syllabi(db, tenant.id, None, None, split_course_id=str(sc_id))}


@router.post("/masterdata/import/darsyar-courses", status_code=201)
def import_darsyar_courses(payload: DarsyarRows, request: Request,
                           actor: Actor = Depends(require_roles(*WRITE_ROLES)),
                           tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.upsert_darsyar_courses(db, tenant.id, actor, payload.rows, request=request)
    db.commit()
    return out


@router.post("/masterdata/syllabi/auto-link")
def auto_link_syllabi(request: Request,
                      actor: Actor = Depends(require_roles(*WRITE_ROLES)),
                      tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    """اتصال مجدد سرفصل‌های بدون پیوند به درس تفکیکی بر تطبیق عنوان (پس از ایمپورت‌های جدید)."""
    linked = svc.link_syllabi_to_split_courses(db, tenant.id)
    db.commit()
    return {"linked": linked}


@router.post("/masterdata/sync/instructors")
def sync_instructors(request: Request,
                     actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                     tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.sync_instructors_from_source(db, tenant.id, actor)


@router.post("/masterdata/sync/classrooms")
def sync_classrooms(request: Request,
                    actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor")),
                    tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return svc.sync_classrooms_from_source(db, tenant.id, actor)


@router.get("/masterdata/fetch-logs")
def fetch_logs(direction: str | None = None, domain: str | None = None, limit: int = 100,
               actor: Actor = Depends(require_roles("steward", "tenant_admin", "master_data_editor", "auditor")),
               tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_logs(db, tenant.id, direction, domain, limit)}


@router.get("/masterdata/service-clients")
def list_clients(actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                 tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"items": svc.list_service_clients(db, tenant.id)}


@router.post("/masterdata/service-clients", status_code=201)
def create_client(payload: ServiceClientCreate, request: Request,
                  actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                  tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.create_service_client(db, tenant.id, actor, payload.model_dump())
    db.commit()
    return out


@router.post("/masterdata/service-clients/{client_id}/revoke")
def revoke_client(client_id: uuid.UUID, request: Request,
                  actor: Actor = Depends(require_roles("steward", "tenant_admin")),
                  tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    out = svc.revoke_service_client(db, tenant.id, client_id)
    db.commit()
    return out


# ---------- سرویس عمومی برای سایر سامانه‌ها (احراز با X-API-Key) ----------


def _service_client_from_key(request: Request, db: Session = Depends(get_db),
                             x_api_key: str | None = Header(default=None)) -> ServiceClient:
    return svc.authenticate_service(db, x_api_key or "")


@router.get("/services/masterdata/{domain}")
def service_masterdata(domain: str, since: str | None = None,
                       tenant_client: ServiceClient = Depends(_service_client_from_key),
                       db: Session = Depends(get_db)):
    """نقطه اتصال همه سامانه‌های اکوسیستم برای گرفتن اطلاعات پایه — هر واکشی لاگ می‌شود."""
    endpoint = f"/api/v1/services/masterdata/{domain}" + (f"?since={since}" if since else "")
    return svc.fetch_domain(db, tenant_client, domain, since, endpoint)
