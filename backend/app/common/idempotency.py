"""کلید Idempotency برای عملیات حساس (بند ۸.۳).

- کلید تکراری با همان ورودی → پاسخ ذخیره‌شده قبلی (اثر جدید ایجاد نمی‌شود)
- کلید تکراری با ورودی متفاوت → رد (409 IDEMPOTENCY_KEY_REUSED)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import conflict
from app.core.security import Actor


def payload_hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class IdempotentResult:
    status: int
    body: dict
    replayed: bool = False


def execute_idempotent(session: Session, tenant_id, key: str | None, actor: Actor,
                       request_payload, produce, fallback_status: int = 201) -> IdempotentResult:
    """produce() تغییرات را روی نشست اعمال می‌کند (بدون commit) و (status, body) برمی‌گرداند.

    ثبت رکورد idempotency در همان تراکنش داده انجام می‌شود؛ commit نهایی اینجا است.
    """
    from app.modules.synchronization.models import IdempotencyRecord

    req_hash = payload_hash(request_payload)

    def _lookup():
        if not key:
            return None
        return session.query(IdempotencyRecord).filter_by(tenant_id=tenant_id, key=key).first()

    existing = _lookup()
    if existing is not None:
        if existing.request_hash != req_hash:
            raise conflict("IDEMPOTENCY_KEY_REUSED", "این کلید Idempotency قبلاً با ورودی متفاوتی استفاده شده است.")
        return IdempotentResult(status=existing.response_status, body=existing.response_body, replayed=True)

    status, body = produce()
    if key:
        session.add(IdempotencyRecord(
            tenant_id=tenant_id, key=key, actor_id=actor.audit_id(), request_hash=req_hash,
            response_status=status, response_body=body,
        ))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = _lookup()
            if existing is None:
                raise
            if existing.request_hash != req_hash:
                raise conflict("IDEMPOTENCY_KEY_REUSED", "این کلید Idempotency قبلاً با ورودی متفاوتی استفاده شده است.")
            return IdempotentResult(status=existing.response_status, body=existing.response_body, replayed=True)
        return IdempotentResult(status=status, body=body)
    session.commit()
    return IdempotentResult(status=status, body=body)
