"""احراز هویت و ورود یکپارچه با SSO سازمان (پرتال دانشجویار۳۶۰).

سه مسیر پشتیبانی می‌شود:
1. جریان فرانت با PKCE: POST /auth/token (پروکسی تبادل کد — بدون CORS).
2. ورود یک‌کلیکی سراسری: GET /auth/sso/login → ریدایرکت به IdP → GET /auth/sso/callback → بازگشت توکن به SPA.
   (قرارداد اکوسیستم: login_url هر سامانه مثل http://188.212.96.235:8094/auth/sso/login)
3. GET /auth/sso/config — پیکربندی عمومی SSO این سامانه (مطابق سایر سامانه‌های اکوسیستم).
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import oidc_metadata

router = APIRouter(tags=["auth"])

_FLOW_COOKIE = "core_sso_flow"
_FLOW_TTL = 600  # ثانیه


class TokenExchange(BaseModel):
    model_config = {"extra": "forbid"}
    code: str = Field(min_length=4)
    code_verifier: str = Field(min_length=16)
    redirect_uri: str


def _public_base(request: Request) -> str:
    if settings.OIDC_PUBLIC_BASE_URL:
        return settings.OIDC_PUBLIC_BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


def _exchange_code(code: str, verifier: str, redirect_uri: str) -> dict:
    doc = oidc_metadata()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "client_id": settings.OIDC_CLIENT_ID,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if settings.OIDC_AUDIENCE:
        data["audience"] = settings.OIDC_AUDIENCE
    # client_secret_post روش اعلام‌شده‌ی SSO است؛ secret هرگز به کلاینت ارسال نمی‌شود
    secret = settings.OIDC_CLIENT_SECRET or ""
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


@router.post("/auth/token")
def exchange_token(payload: TokenExchange):
    return _exchange_code(payload.code, payload.code_verifier, payload.redirect_uri)


@router.get("/auth/authorize-url")
def authorize_url(redirect_uri: str):
    """ساخت URL ورود SSO (state و PKCE در فرانت تولید می‌شوند)."""
    doc = oidc_metadata()
    return {"authorization_endpoint": doc["authorization_endpoint"], "client_id": settings.OIDC_CLIENT_ID,
            "redirect_uri": redirect_uri, "scope": "openid profile email"}


@router.get("/auth/sso/config")
def sso_config(request: Request):
    """پیکربندی عمومی ورود یکپارچه — قرارداد مشترک اکوسیستم دانشجو۳۶۰."""
    base = _public_base(request)
    return {
        "enabled": not settings.DEV_AUTH,
        "issuer": settings.OIDC_ISSUER,
        "client_id": settings.OIDC_CLIENT_ID,
        "app_key": "hr",
        "access_role": settings.SSO_ACCESS_ROLE,
        "scope": "openid profile email",
        "label": "ورود یکپارچه سازمانی",
        "provider": "دانشجویار۳۶۰ — پرتال ورود یکپارچه",
        "login_path": "/auth/sso/login",
        "login_url": f"{base}/auth/sso/login",
        "callback_path": "/auth/sso/callback",
        "redirect_uri": f"{base}/auth/sso/callback",
    }


@router.get("/auth/sso/login")
def sso_login(request: Request):
    """نقطه شروع جریان OIDC سامانه (ورود یک‌کلیکی از پرتال) — state/verifier در کوکی HttpOnly."""
    doc = oidc_metadata()
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(48)  # ≥ 43 کاراکتر — PKCE S256
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    redirect_uri = f"{_public_base(request)}/auth/sso/callback"
    params = {
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid profile email",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    sep = "&" if "?" in doc["authorization_endpoint"] else "?"
    resp = RedirectResponse(doc["authorization_endpoint"] + sep + urlencode(params), status_code=302)
    resp.set_cookie(_FLOW_COOKIE, f"{state}:{verifier}", max_age=_FLOW_TTL,
                    httponly=True, samesite="lax", path="/auth/sso")
    return resp


@router.get("/auth/sso/callback")
def sso_callback(request: Request, code: str = "", state: str = ""):
    """بازگشت از IdP: تبادل کد سراسری و تحویل توکن به SPA با fragment (بدون ورود به لاگ سرور)."""
    raw = request.cookies.get(_FLOW_COOKIE, "")
    expected_state, _, verifier = raw.partition(":")
    if not code or not expected_state or not verifier or state != expected_state:
        return RedirectResponse("/?sso_error=state", status_code=302)
    redirect_uri = f"{_public_base(request)}/auth/sso/callback"
    try:
        tokens = _exchange_code(code, verifier, redirect_uri)
    except AppError as exc:
        return JSONResponse(status_code=exc.status_code, content={
            "code": exc.code, "message": exc.message, "details": exc.details or {}})
    resp = RedirectResponse(f"/#auth={tokens.get('access_token', '')}", status_code=302)
    resp.delete_cookie(_FLOW_COOKIE, path="/auth/sso")
    return resp
