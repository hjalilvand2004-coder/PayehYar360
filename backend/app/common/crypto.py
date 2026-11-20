"""رمزنگاری مقدار حساس (Fernet) و شاخص جست‌وجوی دقیق (HMAC-SHA256).

کلیدها از متغیرهای محیطی/مخزن امن تزریق می‌شوند؛ هرگز در دیتابیس نگه‌داری نمی‌شوند.
"""
from __future__ import annotations

import hashlib
import hmac
import base64

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    raw = settings.ENCRYPTION_KEY
    # کلید متنی dev را به کلید ۳۲بایتی پایه‌64 تبدیل می‌کنیم
    digest = hashlib.sha256(raw.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_value(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_value(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def search_hash(value: str) -> str:
    normalized = " ".join(value.strip().split())
    return hmac.new(settings.SEARCH_HMAC_KEY.encode(), normalized.lower().encode(), hashlib.sha256).hexdigest()


def mask_value(value: str, keep: int = 4) -> str:
    v = value.strip()
    if len(v) <= keep:
        return "*" * len(v)
    return "*" * (len(v) - keep) + v[-keep:]
