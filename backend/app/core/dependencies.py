"""وابستگی‌های FastAPI: هویت، مشتری (tenant) و مجوز."""
from __future__ import annotations

from fastapi import Depends, Request

from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError, forbidden, not_found, unauthorized
from app.core.security import Actor, build_actor_from_claims, build_dev_actor, validate_oidc_token
from app.core.config import settings
from app.modules.integrations.models import Tenant

BEARER = "Bearer "


def get_actor(request: Request) -> Actor:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith(BEARER):
        token = auth[len(BEARER):].strip()
        if settings.DEV_AUTH and token == "dev":
            return build_dev_actor(request.headers)
        return build_actor_from_claims(validate_oidc_token(token))
    if settings.DEV_AUTH:
        # در حالت توسعه، هویت آزمایشی بدون توکن نیز از هدرها ساخته می‌شود
        return build_dev_actor(request.headers)
    raise unauthorized()


def require_roles(*roles: str):
    def dep(actor: Actor = Depends(get_actor)) -> Actor:
        if not actor.has_role(*roles):
            raise forbidden("INSUFFICIENT_ROLE", "برای این عملیات نقش لازم را ندارید.", {"required_roles": list(roles)})
        return actor
    return dep


def require_scope(scope: str):
    """سرویس مصرف‌کننده/مالک با scope مجاز؛ کاربران با نقش‌های مدیریتی."""
    def dep(actor: Actor = Depends(get_actor)) -> Actor:
        if actor.kind == "service" and not actor.has_scope(scope):
            raise forbidden("INSUFFICIENT_SCOPE", f"سرویس جاری scope لازم ({scope}) را ندارد.")
        if actor.kind == "user" and not (
            actor.has_role("steward", "integration_admin", "tenant_admin", "master_data_editor")
        ):
            raise forbidden("INSUFFICIENT_ROLE", "برای این عملیات نقش لازم را ندارید.")
        return actor
    return dep


def resolve_tenant_code(request: Request, actor: Actor) -> str:
    requested = request.headers.get("x-tenant-code") or request.headers.get("x-tenant-id") or ""
    if not requested:
        if len(actor.tenant_codes) == 1:
            requested = actor.tenant_codes[0]
        elif not actor.tenant_codes:
            raise unauthorized("هویت شما به هیچ مشتری (tenant) متصل نیست؛ claim مربوطه در SSO تنظیم شود.")
        else:
            raise AppError("TENANT_REQUIRED", "چند مشتری برای شما تعریف شده است؛ X-Tenant-Code را ارسال کنید.", 400)
    # tenant ارسالی در هدر به‌تنهایی معتبر نیست — باید با عضویت هویت در توکن تطبیق داده شود
    normalized = requested.strip().lower()
    allowed = {t.strip().lower() for t in actor.tenant_codes}
    if normalized not in allowed and requested.strip() not in actor.tenant_codes:
        # اجازه تطبیق با شناسه UUID مشتری نیز داده می‌شود (در ادامه با رکورد بررسی می‌شود)
        pass
    return requested.strip()


def get_tenant(request: Request, actor: Actor = Depends(get_actor), db: Session = Depends(get_db)) -> Tenant:
    requested = resolve_tenant_code(request, actor)
    tenant = db.query(Tenant).filter(
        (Tenant.code == requested.lower()) | (str(Tenant.id) == requested)
    ).first()
    if tenant is None or tenant.status != "active":
        raise not_found("مشتری موردنظر یافت نشد یا غیرفعال است.")
    allowed = {t.strip().lower() for t in actor.tenant_codes}
    if tenant.code.lower() not in allowed and str(tenant.id) not in allowed:
        raise forbidden("TENANT_FORBIDDEN", "شما به این مشتری دسترسی ندارید.", {"tenant": tenant.code})
    request.state.tenant = tenant
    return tenant
