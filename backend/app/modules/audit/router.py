"""API ممیزی — فقط خواندن و جست‌وجوی سوابق مجاز (FR-16)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_actor, get_tenant, require_roles
from app.core.security import Actor
from app.modules.audit.models import AuditLog
from app.modules.integrations.models import Tenant

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("")
def list_audit(entity_type: str | None = None, entity_id: str | None = None,
               operation: str | None = None, actor_id: str | None = None,
               date_from: datetime | None = None, date_to: datetime | None = None,
               limit: int = 50, offset: int = 0,
               actor: Actor = Depends(require_roles("auditor", "tenant_admin", "steward", "integration_admin")),
               tenant: Tenant = Depends(get_tenant), db: Session = Depends(get_db)):
    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant.id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if operation:
        stmt = stmt.where(AuditLog.operation.ilike(f"%{operation}%"))
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id.ilike(f"%{actor_id}%"))
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditLog.created_at <= date_to)
    from sqlalchemy import func
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = list(db.execute(stmt.order_by(AuditLog.created_at.desc())
                           .limit(max(1, min(limit, 200))).offset(offset)).scalars().all())
    return {"total": int(total), "items": [{
        "id": str(r.id), "actor_id": r.actor_id, "actor_name": r.actor_name,
        "actor_type": r.actor_type, "operation": r.operation, "entity_type": r.entity_type,
        "entity_id": r.entity_id, "before": r.before, "after": r.after,
        "ip": r.ip, "correlation_id": r.correlation_id, "note": r.note,
        "created_at": r.created_at.isoformat(),
    } for r in rows]}
