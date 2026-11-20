# سند ۰۱ — معماری

## ۱. نمای استقرار

```
                           کاربران مدیریتی
                            │
                     React Frontend  (nginx — پورت 8094)
                            │ /api/**
                    ┌───────▼────────┐
                    │   FastAPI Core │
                    │ اشخاص/سازمان/مرجع│
                    │ شناسه/مالکیت/Sync│
                    │ کیفیت داده/ممیزی │
                    └───────┬────────┘
                            │
                      PostgreSQL
                       │         │
                 Outbox Worker  Snapshot/Job Worker
                       │
                    RabbitMQ (topic exchange)
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
        آموزشی       پژوهش      سایر سامانه‌ها
        DB محلی      DB محلی      DB محلی
```

- **SSO موجود (`http://188.212.96.235:8086`)** دوباره ساخته نمی‌شود؛ هسته توکن OIDC آن را اعتبارسنجی می‌کند و فرانت از Authorization Code + PKCE استفاده می‌کند.
- حتی با وجود Gateway/nginx، **Backend کنترل مجوز را مستقل انجام می‌دهد** (بند ۵.۱ سند فنی).
- رویدادهای تخصصی (مثل `CourseUpdated`) از سامانه مالک منتشر می‌شوند؛ هسته واسطه اجباری تبادل‌ها نیست.

## ۲. معماری داخلی (یکپارچه ماژولار)

هر ماژول ساختار یکسان دارد: `router.py` (API نازک) → `service.py` (قواعد کسب‌وکار) → `repository.py` (دسترسی داده) + `models.py` + `schemas.py`. منطق کسب‌وکار در router قرار نمی‌گیرد.

```
app/
├── main.py               # سرهم‌بندی، middlewareها، health/metrics، سرو SPA
├── core/                 # config, database, security (OIDC), dependencies (tenant/roles), errors
├── common/               # db base, events (changelog+outbox+audit), idempotency, crypto, statuses
├── modules/
│   ├── persons/          # اشخاص، شناسه‌ها، تماس‌ها
│   ├── organizations/    # ساختار سازمانی (منع چرخه)
│   ├── references/       # فهرست‌های مرجع نسخه‌بندی‌شده
│   ├── identities/       # اتصال حساب SSO + نگاشت شناسه + entity_registry
│   ├── ownership/        # سیاست مالکیت و کنترل ویرایش
│   ├── change_requests/  # درخواست اصلاح و اعمال پس از تأیید
│   ├── data_quality/     # تکرار، پرونده، ادغام/بازگردانی
│   ├── synchronization/  # change_log، outbox، snapshot، checkpoint، idempotency
│   ├── integrations/     # مشتری‌ها، نصب‌ها، وضعیت اتصال
│   └── audit/            # ممیزی فقط-افزودن
├── messaging/rabbitmq.py # Publisher Confirm، persistent، topic
└── workers/              # outbox_worker، job_worker (در کامپوز جدا مستقر می‌شوند)
```

## ۳. زنجیره اجرای درخواست تغییر (بند ۶.۲)

```
اعتبارسنجی هویت (JWT/OIDC یا dev headers)
→ تعیین مشتری معتبر (تطبیق با claimهای توکن — هدر به‌تنهایی معتبر نیست)
→ کنترل مجوز عملیات و فیلد (نقش‌های منطقی)
→ کنترل مالکیت داده (ownership_policies)
→ کنترل نسخه (If-Match در شرط UPDATE)
→ اعتبارسنجی قواعد (Pydantic + service)
→ تراکنش واحد: داده + ChangeLog + Outbox + Audit
→ پاسخ با قرارداد خطای یکسان
```

Middlewareها: Correlation-Id → Rate-limit/Metrics → CORS. کلید Idempotency برای عملیات حساس در همان تراکنش ثبت می‌شود.

## ۴. مرزبندی با اجزای موجود

| جزء | مسئولیت | کاری که هسته نمی‌کند |
|---|---|---|
| SSO | حساب ورود، توکن، نشست | — هسته نگاشت حساب↔شخص را نگه می‌دارد، نه حساب |
| زیرسامانه آموزشی | دانشجو، ثبت‌نام، درس، نمره | وضعیت تحصیلی در هسته ذخیره نمی‌شود |
| زیرساخت داده (دسته ۱) | Data Mart و AI | هسته داده تخصصی نگه نمی‌دارد |
| گراف دانش (دسته ۱۲) | روابط معنایی | از شناسه‌های معتبر هسته می‌خواند؛ ویرایش نمی‌کند |

## ۵. دو الگوی استقرار داده (بند ۷.۱)

- **اختصاصی:** دیتابیس مجزا برای هر مشتری — فقط `DATABASE_URL` هر نصب عوض می‌شود؛ کد بدون تغییر.
- **چندمشتری:** جداسازی با `tenant_id` در همه جدول‌ها + کلیدهای مرکب (`tenant_id, id`) برای منع عبور ارجاع بین مشتری‌ها + کنترل عضویت در API. (RLS در PostgreSQL به‌عنوان دفاع تکمیلی در فاز بعد توصیه شده و در ADR ثبت است.)

## ۶. حالت مستقل و یکپارچه

- **مستقل:** زیرسامانه منتخب + نمونه محلی هسته + PostgreSQL + Worker + RabbitMQ + اتصال به SSO. هسته اطلاعات پایه به‌تنهایی استقلال ورود را تضمین نمی‌کند.
- **یکپارچه:** هر زیرسامانه نسخه محلی محدود دارد و از API/رویدادهای منابع معتبر تغذیه می‌شود؛ در دیتابیس هسته مستقیم نمی‌نویسد. نقطه تعویض در `SharedDataProvider` (LocalCoreAdapter / IntegratedCoreAdapter) پیش‌بینی شده — نمونه مصرف‌کننده (`examples/sample_consumer/consumer.py`) این الگو را نشان می‌دهد.
