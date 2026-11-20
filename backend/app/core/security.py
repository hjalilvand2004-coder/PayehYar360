"""هویت، نقش‌ها و اعتبارسنجی توکن SSO (OIDC/OAuth2 — RS256).

- توکن کاربر و سرویس از SSO موجود سازمان اعتبارسنجی می‌شود (issuer، امضا، انقضا، مخاطب).
- در حالت توسعه (DEV_AUTH=true) هدرهای X-Dev-* هویت آزمایشی می‌سازند — مطلقاً فقط برای dev/test.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import settings
from app.core.errors import AppError, unauthorized

log = logging.getLogger("core.security")

KNOWN_ROLES = {
    "viewer": "مشاهده‌گر اطلاعات پایه",
    "master_data_editor": "کارشناس اطلاعات پایه",
    "steward": "متولی داده",
    "integration_admin": "مدیر یکپارچگی",
    "auditor": "ممیز",
    "tenant_admin": "مدیر مشتری",
}

SERVICE_SCOPES = {"owner", "read", "sync"}


@dataclass
class Actor:
    kind: str  # user | service
    subject: str
    name: str
    roles: set[str] = field(default_factory=set)
    scopes: set[str] = field(default_factory=set)  # برای سرویس‌ها: owner:person و ...
    tenant_codes: list[str] = field(default_factory=list)
    issuer: str = ""
    client_id: str = ""
    claims: dict = field(default_factory=dict)

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles & set(roles))

    def has_scope(self, scope: str) -> bool:
        if scope in self.scopes or "*" in self.scopes:
            return True
        # owner:<entity> شامل read همان موجودیت است
        if scope.startswith("read:") and f"owner:{scope[5:]}" in self.scopes:
            return True
        return False

    def audit_id(self) -> str:
        return f"{self.kind}:{self.subject}"


_oidc_cache: dict = {"discovery": None, "fetched_at": 0.0, "jwk_client": None}


def _discovery() -> dict:
    now = time.time()
    if _oidc_cache["discovery"] and now - _oidc_cache["fetched_at"] < 3600:
        return _oidc_cache["discovery"]
    url = settings.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration"
    with httpx.Client(timeout=settings.OIDC_HTTP_TIMEOUT) as client:
        resp = client.get(url)
        resp.raise_for_status()
        doc = resp.json()
    if doc.get("issuer", "").rstrip("/") != settings.OIDC_ISSUER.rstrip("/"):
        raise AppError("OIDC_ISSUER_MISMATCH", "issuer پیکربندی‌شده با SSO مطابقت ندارد.", 500)
    _oidc_cache["discovery"] = doc
    _oidc_cache["fetched_at"] = now
    _oidc_cache["jwk_client"] = None
    return doc


def jwk_client() -> PyJWKClient:
    if _oidc_cache["jwk_client"] is None:
        jwks_uri = _discovery()["jwks_uri"]
        _oidc_cache["jwk_client"] = PyJWKClient(jwks_uri, cache_keys=True, lifespan=600)
    return _oidc_cache["jwk_client"]


def oidc_metadata() -> dict:
    return _discovery()


def validate_oidc_token(token: str) -> dict:
    try:
        key = jwk_client().get_signing_key_from_jwt(token).key
    except Exception as exc:
        log.warning("JWKS lookup failed: %s", exc)
        raise unauthorized("امضای توکن قابل بررسی نیست (کلید SSO در دسترس نیست یا توکن نامعتبر است).")
    options = {"verify_aud": bool(settings.OIDC_AUDIENCE)}
    try:
        claims = jwt.decode(
            token, key=key, algorithms=["RS256"],
            issuer=settings.OIDC_ISSUER.rstrip("/"),
            audience=settings.OIDC_AUDIENCE or None,
            options=options, leeway=60,
        )
    except jwt.ExpiredSignatureError:
        raise unauthorized("توکن منقضی شده است.")
    except jwt.InvalidTokenError as exc:
        log.warning("Invalid token: %s", exc)
        raise unauthorized("توکن ارسالی معتبر نیست.")
    return claims


def extract_raw_roles(claims: dict) -> set[str]:
    """همه نقش‌های قابل استخراج از توکن — بدون فیلتر (شامل نقش‌های سامانه‌ای مثل hr.access)."""
    roles: set[str] = set()
    for source in (claims.get("core_roles"), claims.get("roles"),
                   (claims.get("realm_access") or {}).get("roles")):
        if isinstance(source, list):
            roles.update(r for r in source if isinstance(r, str))
    resource = claims.get("resource_access") or {}
    if isinstance(resource, dict):
        for client_cfg in resource.values():
            if isinstance(client_cfg, dict) and isinstance(client_cfg.get("roles"), list):
                roles.update(r for r in client_cfg["roles"] if isinstance(r, str))
    return roles


def extract_roles(claims: dict) -> set[str]:
    return extract_raw_roles(claims) & set(KNOWN_ROLES)


def has_sso_access(claims: dict) -> bool:
    """آیا توکن نقش دسترسی سازمانی اکوسیستم را دارد؟ (قرارداد: <appKey>.access)"""
    raw = extract_raw_roles(claims)
    aliases = {settings.SSO_ACCESS_ROLE, "hr.access", "payeh360.access", "payehyar.access"}
    return bool(raw & aliases)


def extract_tenants(claims: dict) -> list[str]:
    vals = claims.get("tenants") or claims.get("tenant") or claims.get("tenant_code")
    if isinstance(vals, str):
        vals = [vals]
    if not isinstance(vals, list):
        return []
    return [str(v) for v in vals if str(v)]


def build_actor_from_claims(claims: dict) -> Actor:
    kind = "service" if claims.get("actor_type") == "service" or claims.get("token_type") == "service" else "user"
    subject = str(claims.get("sub") or "")
    if not subject:
        raise unauthorized("توکن فاقد subject است.")
    scopes = set()
    raw_scopes = claims.get("scopes") or claims.get("scope") or []
    if isinstance(raw_scopes, str):
        raw_scopes = raw_scopes.split()
    for s in raw_scopes:
        if ":" in s:
            head, ent = s.split(":", 1)
            if head in SERVICE_SCOPES:
                scopes.add(f"{head}:{ent}")
        elif s == "*":
            scopes.add("*")
    roles = extract_roles(claims)
    tenant_codes = extract_tenants(claims)
    # کاربر سازمانی با نقش دسترسی اکوسیستم: حداقل مشاهده‌گر + مشتری پیش‌فرض پایلوت
    if kind == "user" and has_sso_access(claims):
        roles = roles | {"viewer"}
        if not tenant_codes and settings.SSO_DEFAULT_TENANT:
            tenant_codes = [settings.SSO_DEFAULT_TENANT]
    return Actor(
        kind=kind,
        subject=subject,
        name=str(claims.get("name") or claims.get("preferred_username") or claims.get("client_id") or subject),
        roles=roles,
        scopes=scopes,
        tenant_codes=tenant_codes,
        issuer=str(claims.get("iss") or ""),
        client_id=str(claims.get("client_id") or claims.get("azp") or ""),
        claims=claims,
    )


def build_dev_actor(headers) -> Actor:
    """فقط برای توسعه: هویت آزمایشی از هدرها — DEV_AUTH باید فعال باشد."""
    subject = headers.get("x-dev-user", "").strip()
    if not subject:
        raise unauthorized("در حالت توسعه، هدر X-Dev-User الزامی است.")
    roles = {r.strip() for r in headers.get("x-dev-roles", "").split(",") if r.strip()} & set(KNOWN_ROLES)
    tenants = [t.strip() for t in headers.get("x-dev-tenants", "").split(",") if t.strip()]
    scopes = {s.strip() for s in headers.get("x-dev-scopes", "").split()
              if ":" in s or s == "*" or s.strip() in SERVICE_SCOPES}
    kind = "service" if headers.get("x-dev-service") else "user"
    return Actor(
        kind=kind,
        subject=subject,
        name=headers.get("x-dev-name") or subject,
        roles=roles,
        scopes=scopes,
        tenant_codes=tenants,
        issuer="dev",
        client_id=headers.get("x-dev-service") or "",
        claims={"dev": True},
    )
