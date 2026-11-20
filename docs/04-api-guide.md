# سند ۰۴ — راهنمای API

Base URL: `http://188.212.96.235:8094/api/v1` — مستند تعاملی: `/docs` (Swagger UI) و `/openapi.json`.
زمان‌ها UTC (ISO-8601)؛ شناسه‌ها UUID؛ پاسخ خطا طبق قرارداد بخش ۸.۳.

## ۱. مسیرهای اصلی

| روش و مسیر | کاربرد | مجوز |
|---|---|---|
| GET `/persons?q=&status=&identifier_type=&identifier_value=` | جست‌وجوی محدود و مجاز | هویت معتبر؛ جست‌وجوی شناسه: نقش‌های مجاز |
| POST `/persons` | ایجاد شخص | مالک group general (کارشناس/متولی) — `Idempotency-Key` پشتیبانی |
| GET `/persons/{id}` | مشخصات مجاز شخص | هویت معتبر |
| PATCH `/persons/{id}` | اصلاح با کنترل نسخه | مالک general + هدر `If-Match: "نسخه"` |
| POST `/persons/{id}/deactivation` | غیرفعال‌سازی | مالک status (متولی) + If-Match |
| GET `/persons/{id}/history` | سابقه تغییر از change_log | هویت معتبر |
| POST/PATCH `/persons/{id}/identifiers[/{iid}]` | شناسه‌ها (ثبت/تأیید/ابطال) | مالک identifiers (متولی) |
| POST/PATCH `/persons/{id}/contacts[/{cid}]` | تماس‌ها | مالک contacts |
| GET `/identity/me` | شخص متناظر حساب جاری | هویت معتبر |
| POST `/identity-account-links` | اتصال کنترل‌شده حساب | متولی/مدیر یکپارچگی/مدیر مشتری — Idempotency-Key |
| POST `/identity-account-links/{id}/revoke` | قطع حساب | همان بالا |
| GET/POST `/organizations`, PATCH `/organizations/{id}` | ساختار سازمانی (منع چرخه) | مالک general |
| GET/POST `/reference-sets`, `/reference-sets/{code}/items` | فهرست‌های مرجع | خواندن: همه؛ نوشتن: مالک |
| POST `/id-mappings` | ثبت نگاشت | نقش‌ها یا scope مالکیت سرویس — Idempotency-Key |
| POST `/id-mappings/resolve` | تبدیل شناسه محلی | همه هویت‌ها + سرویس مصرف‌کننده |
| GET `/id-mappings` | فهرست نگاشت‌ها | هویت معتبر |
| GET/PUT `/ownership-policies` | مشاهده/تغییر مالکیت | تغییر: متولی/مدیر (ممیزی کامل) |
| POST/GET `/change-requests`, POST `/change-requests/{id}/decision` | درخواست اصلاح | ایجاد: همه هویت‌ها؛ تصمیم: متولی |
| GET `/quality/duplicate-scan`, POST `/quality/cases` | کشف و پرونده تکرار | متولی/کارشناس/مدیر |
| POST `/resolution-cases/{id}/merge`, POST `/merges/{id}/reverse`, GET `/merges` | ادغام و بازگردانی | متولی (تأیید دوباره در UI) |
| POST `/sync/snapshots`, GET `/sync/snapshots/{id}` (+`/download`) | Snapshot | scope `sync` یا نقش‌های مدیریتی — Idempotency-Key |
| GET `/sync/changes?cursor=&limit=` | تغییرات جبرانی | scope `sync`؛ cursor منقضی → **410** |
| POST `/sync/checkpoints` | اعلام نقطه پردازش | scope `sync` |
| POST `/sync/reconciliation/jobs` | تطبیق پایه | scope `sync` |
| GET/POST `/tenants`, GET/POST/PATCH `/installations` | مشتری و نصب‌ها | مدیر یکپارچگی/مدیر مشتری |
| GET `/integrations/status`, GET `/stats` | پایش و داشبورد | هویت معتبر |
| GET `/audit-logs` | ممیزی (فقط خواندن) | ممیز/مدیر/متولی/مدیر یکپارچگی |
| GET `/meta` | اطلاعات حالت auth و SSO | عمومی |

Health: `/health/live`, `/health/ready`, `/metrics` (Prometheus).

## ۲. احراز هویت درخواست

- **تولید:** `Authorization: Bearer <JWT-SSO>` (RS256، issuer=`http://188.212.96.235:8086`) + هدر `X-Tenant-Code` (باید با claim `tenants` توکن تطبیق داشته باشد؛ هدر به‌تنهایی معتبر نیست).
- **توسعه (فقط `DEV_AUTH=true`):** `Authorization: Bearer dev` + `X-Dev-User`, `X-Dev-Roles` (جدا با کاما), `X-Dev-Tenants`, `X-Dev-Scopes` (برای سرویس)، `X-Dev-Service`.

## ۳. نمونه اصلاح شخص (بند ۸.۲)

```http
PATCH /api/v1/persons/{person_id}
Authorization: Bearer ...
If-Match: "12"
Content-Type: application/json

{ "display_name": "نام اصلاح‌شده" }
```

پاسخ موفق:

```json
{ "id": "uuid", "display_name": "نام اصلاح‌شده", "version": 13 }
```

کنترل نسخه در شرط `UPDATE ... WHERE version = 12` انجام می‌شود؛ تعارض → `412 VERSION_CONFLICT` با `details.current_version`.

## ۴. قرارداد خطا

```json
{ "code": "DATA_OWNER_MISMATCH",
  "message": "ویرایش این داده فقط توسط مرجع معتبر مجاز است.",
  "correlation_id": "uuid" }
```

| کد HTTP | کاربرد | codeهای رایج |
|---|---|---|
| 401 | هویت نامعتبر | UNAUTHENTICATED |
| 403 | عملیات غیرمجاز | DATA_OWNER_MISMATCH, INSUFFICIENT_ROLE, INSUFFICIENT_SCOPE, TENANT_FORBIDDEN |
| 404 | یافت نشد/خارج از محدوده | NOT_FOUND |
| 409 | تعارض کسب‌وکار | MAPPING_CONFLICT, ACCOUNT_ALREADY_LINKED, IDEMPOTENCY_KEY_REUSED, ORG_CYCLE |
| 412 | تعارض نسخه | VERSION_CONFLICT |
| 422 | ورودی نامعتبر | INVALID_INPUT |
| 429 | محدودیت نرخ | RATE_LIMITED |
| 410 | cursor منقضی | CURSOR_EXPIRED |

هر پاسخ سرور هدر `X-Correlation-Id` دارد.

## ۵. Idempotency

برای عملیات حساس (ایجاد شخص، اتصال حساب، ثبت نگاشت، ایجاد Snapshot) هدر `Idempotency-Key` ارسال کنید:

- کلید تکراری + ورودی یکسان → همان پاسخ قبلی + هدر `Idempotent-Replay: true` (بدون اثر جدید)
- کلید تکراری + ورودی متفاوت → `409 IDEMPOTENCY_KEY_REUSED`
