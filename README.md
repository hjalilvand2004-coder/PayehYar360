# هسته مشترک و اطلاعات پایه — دانشجو۳۶۰ / PayehYar360 (Shared Core & Master Data)

پیاده‌سازی «سند فنی تولید زیرسیستم هسته مشترک و اطلاعات پایه» پلتفرم دانشجو۳۶۰ — شرکت ماه‌افزار هوشمند رسا.

این هسته، **مرجع هویت عمومی، شناسه‌های مشترک، اطلاعات پایه مصوب و خدمات همگام‌سازی** است؛ نه پایگاه داده مرکزیِ همه زیرسامانه‌ها و نه جایگزین SSO.

## دانلود نسخه‌ها (Releases)

| بسته | کاربرد |
|---|---|
| `PayehYar360-Portable-Windows-*.zip` | اجرا روی ویندوز **بدون نیاز به نصب Python/PyCharm** — پایتون embeddable و همه وابستگی‌ها داخل بسته است؛ اجرا با `start.bat` |
| `PayehYar360-Portable-Linux-*.zip` | اجرا روی لینوکس x86_64 بدون Python — باینری مستقل PyInstaller |
| Source code (zip/tar.gz) | کد کامل + Docker deployment |

پس از استخراج: `cd PayehYar360-Portable-Windows && start.bat` → پنل روی `http://localhost:8094` با ورود آزمایشی (حالت dev) باز می‌شود.


| مشخصه | مقدار |
|---|---|
| Backend | FastAPI / Python 3.12 (معماری ماژولار) |
| Frontend | React 18 + TypeScript + Vite (RTL فارسی) |
| پایگاه داده | PostgreSQL (حالت توسعه: SQLite) |
| ارتباط رویدادمحور | RabbitMQ + الگوی Outbox/Inbox/ChangeLog |
| احراز هویت | OIDC/OAuth2 متصل به SSO موجود (`http://188.212.96.235:8086`) |
| استقرار | Docker Compose — انتشار روی پورت **8094** |

## شروع سریع (محیط توسعه)

```bash
# 1) Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DEV_AUTH=true AUTO_CREATE_TABLES=true SEED_DEMO=true \
WORKERS_IN_PROCESS=true DATABASE_URL="sqlite:///../data/demo.db" \
SERVE_FRONTEND_DIR="$(pwd)/../frontend/dist" \
uvicorn app.main:app --port 8094

# 2) Frontend (فقط برای توسعه با HMR)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

سپس `http://localhost:8094` — پنل با «ورود آزمایشی» باز می‌شود (فقط dev؛ در تولید ورود از پرتال SSO انجام می‌شود). مشتری دمو `demo` با نقش‌های پیشنهادی steward/tenant_admin.

## شروع سریع (استقرار روی سرور — پورت 8094)

```bash
cd deploy
cp env.example .env         # رمزها و کلیدهای رمزنگاری را کامل کنید
docker compose up -d --build
# → http://188.212.96.235:8094
```

سرویس‌های قابل استقرار: `core-api`، `core-frontend` (nginx)، `core-outbox-worker`، `core-job-worker`، `postgresql`، `rabbitmq`. جزئیات: [docs/07-deployment.md](docs/07-deployment.md).

## ساختار مخزن

```
backend/     FastAPI — app/core (config/security/tenancy/errors) + app/modules (اشخاص، سازمان، مرجع، هویت، مالکیت، همگام‌سازی، کیفیت، ممیزی، یکپارچگی) + workers + messaging + migrations (Alembic) + tests
frontend/    React/TS — ۱۱ صفحه پنل مدیریتی RTL + auth (OIDC PKCE + حالت dev)
examples/    نمونه مصرف‌کننده با Inbox و نسخه محلی (consumer.py)
deploy/      Dockerfile ها، docker-compose.yml، nginx.conf، env.example
docs/        مستندات فنی (۱۰ سند فارسی)
```

## مستندات

| سند | محتوا |
|---|---|
| [۰۱ معماری](docs/01-architecture.md) | نمای استقرار، زنجیره درخواست، مرزبندی با SSO و زیرسامانه‌ها |
| [۰۲ مدل داده](docs/02-data-model.md) | ERD و Data Dictionary کامل ۲۴ جدول |
| [۰۳ ماتریس مالکیت](docs/03-ownership-matrix.md) | مالکیت موجودیت/ویژگی و قواعد کنترل ویرایش |
| [۰۴ راهنمای API](docs/04-api-guide.md) | مسیرها، قرارداد خطا، نمونه‌ها، Idempotency و If-Match |
| [۰۵ رویدادها و همگام‌سازی](docs/05-events-and-sync.md) | قرارداد پیام، Outbox/Inbox، Snapshot، cursor و checkpoint |
| [۰۶ اتصال SSO](docs/06-sso-integration.md) | OIDC واقعی سرور 8086، نگاشت claim و نقش‌ها |
| [۰۷ استقرار و عملیات](docs/07-deployment.md) | Docker، متغیرها، پشتیبان‌گیری، TLS، پایش |
| [۰۸ راهنمای کاربری پنل](docs/08-user-guide.md) | راهنمای ۱۱ صفحه پنل مدیریتی |
| [۰۹ آزمون و پذیرش](docs/09-testing.md) | لایه‌های آزمون و نگاشت سناریوهای الزامی ۱۵.۲ |
| [۱۰ تصمیمات معماری](docs/10-adr.md) | ADR و محدودیت‌های شناخته‌شده |

## پوشش نیازمندی‌های FR

FR-01 تا FR-13 و FR-15 تا FR-17 در سطح MVP/پایه پیاده‌سازی شده‌اند؛ FR-14 (مهاجرت نصب مستقل به یکپارچه) ابزار و گزارش پایه دارد و تکمیل نهایی آن مرحله بعد است (هم‌راستا با بند ۱۶ سند). ردیابی کامل در [docs/09-testing.md](docs/09-testing.md).

## وضعیت اعتبارسنجی

- ۳۸/۳۸ آزمون pytest سبز — شامل سناریوهای الزامی ۱۵.۲ (تعارض نسخه، Idempotency، جداسازی مشتری، غیرمالک، تکرار پیام، قطع RabbitMQ، cursor منقضی، ادغام/بازگردانی، Snapshot بدون شکاف) و ۵ آزمون جدید v1.0.13 برای سرویس‌دهی به سامانه یادگیری هوشمند.

## v1.0.13 — رفع باگ واکشی درس تفکیکی + ETag برای سامانه یادگیری هوشمند

- **رفع باگ استقرار زنده:** واکشی دامنه `split-courses` با `NameError: name 'uc' is not defined` (HTTP 500) شکست می‌خورد — ترتیب‌دهی کوئری داخل list comprehension به متغیرهای حلقه ارجاع می‌داد؛ اکنون با ویژگی کلاس ORM پیش از اجرا.
- **ETag/304:** هر پاسخ `/api/v1/services/masterdata/{domain}` هدر `ETag` دارد؛ If-None-Match تطبیق‌یافته → 304 بدون انتقال بدنه (لاگ واکشی با items_returned=0).
- **نام جایگزین `syllabi`:** معادل `course-syllabi` طبق سند فنی اتصال — هر دو نام معتبرند.
- **CORS:** مبداهای سامانه یادگیری هوشمند (`:8084` محلی/سرور) به `ALLOWED_ORIGINS` اضافه و هدر `ETag` در `expose_headers` قرار گرفت.
- تست: `tests/test_service_fetch_v1013.py` — split-courses بدون NameError، هم‌ارزی alias، ابطال ETag پس از تغییر، دلتای since، حفظ SCOPE_FORBIDDEN.
- Smoke test یکپارچه: سرور پورت 8094 (API + فرانت)، Snapshot تولیدشده با مرز بدون شکاف، resolve نگاشت و داشبورد بررسی شد.
