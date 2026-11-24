"""تنظیمات مرکزی هسته مشترک — همه مقادیر از متغیرهای محیطی خوانده می‌شود."""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    ENV: str = "dev"  # dev | test | prod

    # --- دیتابیس ---
    DATABASE_URL: str = "postgresql+psycopg://core:CHANGE_ME@localhost:5432/shared_core"
    AUTO_CREATE_TABLES: bool = False  # فقط برای توسعه/دمو؛ در تولید از Alembic استفاده شود
    SEED_DEMO: bool = False           # بارگذاری داده نمونه دمو (فقط dev/test)
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # --- SSO / OIDC ---
    # issuer واقعی SSO موجود سازمان (پرتال ورود یکپارچه دانشجویار۳۶۰ — Keycloak-سازگار)
    # ثبت سامانه در پرتال: appKey=hr، Client ID=payeh360، ورود OIDC=http://188.212.96.235:8094/
    OIDC_ISSUER: str = "http://188.212.96.235:8086"
    OIDC_CLIENT_ID: str = "payeh360"  # client ثبت‌شده در پرتال (Authorization Code + PKCE)
    OIDC_AUDIENCE: str = ""  # اگر خالی باشد بررسی aud انجام نمی‌شود
    OIDC_CLIENT_SECRET: str = ""  # فقط اگر SSO روش محرمانه لازم داشته باشد؛ از مخزن امن تزریق شود
    OIDC_HTTP_TIMEOUT: float = 6.0
    OIDC_PUBLIC_BASE_URL: str = ""  # اگر سامانه پشت پروکسی است، ریشه عمومی (مثلاً http://188.212.96.235:8094)
    # نقش دسترسی سازمانی در SSO — قرارداد اکوسیستم: <appKey>.access
    SSO_ACCESS_ROLE: str = "hr.access"
    # مشتری پیش‌فرض برای کاربران SSO که claim مشتری ندارند (حالت پایلوت)
    SSO_DEFAULT_TENANT: str = "demo"
    # حالت توسعه: پذیرش هدرهای X-Dev-* به‌جای توکن واقعی — فقط در dev/test
    DEV_AUTH: bool = False

    # --- CORS ---
    ALLOWED_ORIGINS: str = ("http://188.212.96.235:8094,http://localhost:8094,http://localhost:5173, "
                            "http://188.212.96.235:8084,http://127.0.0.1:8084,http://localhost:8084")  # ۸۰۸۴ = سامانه یادگیری هوشمند (پرتیبل/استقرار)

    # --- محدودسازی نرخ (0 = خاموش) ---
    RATE_LIMIT_PER_MINUTE: int = 0

    # --- همگام‌سازی ---
    CHANGE_RETENTION_MIN: int = 50000  # عمق نگهداری change_log برای cursor (تعداد)
    SNAPSHOT_TTL_HOURS: int = 24
    OUTBOX_BATCH_SIZE: int = 100
    OUTBOX_POLL_SECONDS: float = 2.0
    OUTBOX_MAX_ATTEMPTS: int = 20
    OUTBOX_RETRY_BASE_SECONDS: float = 3.0
    WORKERS_IN_PROCESS: bool = False  # اجرای workerها داخل فرآیند API (دمو/توسعه)

    # --- منابع داده خارجی برای همگام‌سازی اطلاعات پایه (اساتید/کلاس‌ها) ---
    # واکشی اساتید از سامانه نظرسنجی دروس: کوکی مرورگر با دسترسی admin یا endpoint JSON
    DARSYAR_BASE: str = "https://darsyar360.ir"
    DARSYAR_ADMIN_COOKIE: str = ""   # مثال: "session=...؛ از DevTools مرورگر با لاگین ادمین"
    DARSYAR_INSTRUCTORS_JSON_URL: str = ""  # اگر endpoint JSON برای اساتید در دسترس باشد
    # واکشی کلاس‌ها/سالن‌ها از سامانه برنامه‌ریزی درسی (barnamehyar360)
    SCHEDULER_BASE: str = "http://188.212.96.235:8083"
    SCHEDULER_USERNAME: str = ""     # کاربر دارای دسترسی «کلاس‌ها و سالن‌ها»
    SCHEDULER_PASSWORD: str = ""
    EXTERNAL_HTTP_TIMEOUT: float = 20.0

    # --- RabbitMQ ---
    RABBITMQ_URL: str = ""  # خالی = انتشار غیرفعال؛ رویدادها در Outbox می‌مانند
    RABBITMQ_EXCHANGE: str = "shared-core.events"

    # --- کلیدهای رمزنگاری (در تولید از مخزن امن تزریق شود) ---
    ENCRYPTION_KEY: str = ""   # کلید Fernet برای رمز مقدار شناسه‌های حساس
    SEARCH_HMAC_KEY: str = ""  # کلید HMAC شاخص جست‌وجوی دقیق

    # --- فایل‌ها و فرانت ---
    DATA_DIR: str = "./data"
    SERVE_FRONTEND_DIR: str = ""  # مسیر frontend/dist برای سرو یکپارچه
    API_PREFIX: str = "/api/v1"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # کلیدهای پایدار dev برای جلوگیری از بی‌اعتباری‌شدن شاخص HMAC بین اجراها
    if not s.ENCRYPTION_KEY:
        s.ENCRYPTION_KEY = "dev-only-fernet-key-do-not-use-in-prod__0123456789abcdef"
    if not s.SEARCH_HMAC_KEY:
        s.SEARCH_HMAC_KEY = "dev-only-hmac-key-do-not-use-in-prod__0123456789abcdef"
    return s


settings = get_settings()

os.makedirs(settings.DATA_DIR, exist_ok=True)
