"""پروکسی تبادل کد OAuth2 با SSO — برای جلوگیری از CORS بین فرانت و SSO.

کلاینت عمومی با PKCE؛ اگر OIDC_CLIENT_SECRET تنظیم شده باشد، محرمانه در سمت سرور استفاده می‌شود.
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import oidc_metadata

router = APIRouter(tags=["auth"])


class TokenExchange(BaseModel):
    model_config = {"extra": "forbid"}
    code: str = Field(min_length=4)
    code_verifier: str = Field(min_length=16)
    redirect_uri: str


@router.post("/auth/token")
def exchange_token(payload: TokenExchange):
    doc = oidc_metadata()
    data = {
        "grant_type": "authorization_code",
        "code": payload.code,
        "redirect_uri": payload.redirect_uri,
        "code_verifier": payload.code_verifier,
        "client_id": settings.OIDC_CLIENT_ID,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if settings.OIDC_AUDIENCE:
        data["audience"] = settings.OIDC_AUDIENCE
    # client_secret_post روش اعلام‌شده‌ی SSO است؛ secret هرگز به کلاینت ارسال نمی‌شود
    secret = getattr(settings, "OIDC_CLIENT_SECRET", "") or ""
    if secret:
        data["client_secret"] = secret
    try:
        with httpx.Client(timeout=settings.OIDC_HTTP_TIMEOUT) as client:
            resp = client.post(doc["token_endpoint"], data=data, headers=headers)
    except httpx.HTTPError as exc:
        raise AppError("SSO_UNREACHABLE", f"ارتباط با SSO برقرار نشد: {type(exc).__name__}", 502)
    if resp.status_code != 200:
        raise AppError("SSO_TOKEN_ERROR", "تبادل کد با SSO ناموفق بود.", 401,
                       {"status": resp.status_code, "body": resp.text[:300]})
    return resp.json()


@router.get("/auth/authorize-url")
def authorize_url(redirect_uri: str):
    """ساخت URL ورود SSO (state و PKCE در فرانت تولید می‌شوند)."""
    doc = oidc_metadata()
    return {"authorization_endpoint": doc["authorization_endpoint"], "client_id": settings.OIDC_CLIENT_ID,
            "redirect_uri": redirect_uri, "scope": "openid profile email"}
