# سند ۰۷ — استقرار، عملیات و امنیت

## ۱. استقرار روی 188.212.96.235 — پورت 8094

```bash
# پیش‌نیاز: docker + compose plugin
cd deploy
cp env.example .env
#  - POSTGRES_PASSWORD / RABBITMQ_PASSWORD: رمزهای قوی
#  - ENCRYPTION_KEY / SEARCH_HMAC_KEY: رشته تصادفی ≥۳۲ کاراکتر (openssl rand -hex 32)
#  - OIDC_CLIENT_ID: client PKCE ثبت‌شده روی SSO
nano .env
docker compose up -d --build
docker compose exec core-api python -m alembic upgrade head   # در صورت نیاز
curl http://188.212.96.235:8094/health/ready
```

سرویس‌ها: `core-api` (Migration خودکار پیش از راه‌اندازی)، `core-frontend` (nginx → پورت منتشرشده **8094**)، `core-outbox-worker`، `core-job-worker`، `postgresql`، `rabbitmq`. دیتابیس و RabbitMQ فقط روی شبکه داخلی compose منتشر می‌شوند.

محیط‌ها: توسعه (Compose/SQLite + DEV_AUTH)، آزمون یکپارچگی، پیش‌تولید، تولید. Kubernetes فقط در صورت نیاز عملیاتی و زیرساخت آماده.

## ۲. الزامات عملیاتی (بند ۱۴.۳) — وضعیت

| الزام | وضعیت پیاده‌سازی |
|---|---|
| Migration کنترل‌شده پیش از نسخه جدید | ✅ Alembic در entrypoint core-api؛ تنها یک Replica Migration می‌راند |
| عدم اجرای هم‌زمان Migration توسط همه Replicaها | ✅ فقط core-api اجرا می‌کند (workerها بدون Migration) |
| مدیریت Secret خارج از کد/Image | ✅ env_file + مخزن امن؛ env.example بدون Secret واقعی |
| TLS | ⬜ روی nginx خود سرور/LB سازمانی (ترمینیشن TLS بیرون از container؛ در env ALLOWED_ORIGNS با https به‌روزرسانی شود) |
| محدودسازی CORS | ✅ `ALLOWED_ORIGINS` (پیش‌فرض فقط مبدا 8094) |
| محدودیت حجم/نرخ API و خروجی | ✅ `client_max_body_size` در nginx + `RATE_LIMIT_PER_MINUTE` (429) |
| پشتیبان‌گیری و آزمون بازیابی | فرآیند پایین را ببینید |
| دسترسی حداقلی DB/RabbitMQ | ✅ کاربر اختصاصی core؛ انتشار خارجی پورت‌ها بسته |
| ممیزی حفاظت‌شده | ✅ فقط-افزودن در API؛ در PG پیشنهاد: `REVOKE UPDATE, DELETE ON audit_logs FROM core;` در سند SQL عملیات |

## ۳. پشتیبان‌گیری و بازیابی

```bash
# پشتیبان منطقی روزانه
docker compose exec postgresql pg_dump -U core shared_core | gzip > backup-$(date +%F).sql.gz
# بازیابی
gunzip -c backup-2026-01-01.sql.gz | docker compose exec -T postgresql psql -U core shared_core
```

- آزمون بازیابی به‌صورت دوره‌ای در محیط آزمون انجام شود (سناریوی Recovery بخش ۱۵).
- حجم ChangeLog با `CHANGE_RETENTION_MIN` کنترل و پاکسازی دوره‌ای (Job بعدی) تعریف می‌شود.
- کلیدهای رمزنگاری (ENCRYPTION_KEY/SEARCH_HMAC_KEY) باید از پشتیبان جدا و در مخزن امن نگه‌داری شوند؛ گم‌شدن کلید HMAC، جست‌وجوی شناسه‌های قبلی را بی‌اثر می‌کند.

## ۴. Health و پایش (بند ۱۴.۴)

- `/health/live` — فرآیند زنده
- `/health/ready` — دیتابیس + وضعیت RabbitMQ؛ **قطع Broker وضعیت ready را degrade نمی‌کند** (Outbox تغییرات را نگه می‌دارد)
- `/metrics` — Prometheus: `api_requests_total`, `api_request_seconds_sum`, `outbox_pending`, `outbox_failed`, `outbox_oldest_pending_age_seconds`, `rabbitmq_connected`

شاخص‌های مورد انتظار داشبورد عملیات: زمان پاسخ/نرخ خطای API، سن قدیمی‌ترین Outbox، Retry/صف خطا، زمان تولید Snapshot، فاصله checkpoint مصرف‌کننده از مرجع ( lag در `/integrations/status`)، پرونده‌های کیفیت معوق، سلامت دیتابیس. حد مجاز عقب‌ماندگی Outbox و ظرفیت ذخیره باید عملیاتی تعریف شود.

## ۵. اجرای مهاجرت‌ها و ارتقا

```bash
git pull && docker compose build
docker compose up -d                 # core-api Migration را قبل از سرو می‌راند
docker compose logs -f core-api
```

Rollback: بازگشت به image قبلی + Migration downgrade در صورت لازم (`alembic downgrade -1`) — فقط Migrationهایی که downgrade امن دارند.

## ۶. نکات امنیتی مکمل

- اجرای هسته فقط پشت Gateway/HTTPS سازمانی؛ هدرهای امنیتی پایه در nginx تنظیم شده.
- `/metrics` فقط از شبکه داخلی مجاز است (قوانین nginx).
- لاگ‌ها نباید حاوی مقدار کامل شناسه‌ها باشند (در کد فقط mask/hash ثبت می‌شود).
