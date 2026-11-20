# سند ۰۶ — اتصال SSO موجود

## ۱. قرارداد واقعی سرور (استخراج‌شده از `http://188.212.96.235:8086`)

| ویژگی | مقدار |
|---|---|
| نوع | OIDC/OAuth2 Provider (سبک Keycloak، issuer در ریشه) |
| issuer | `http://188.212.96.235:8086` |
| discovery | `/.well-known/openid-configuration` |
| authorization_endpoint | `/protocol/openid-connect/auth` |
| token_endpoint | `/protocol/openid-connect/token` |
| jwks_uri | `/protocol/openid-connect/certs` |
| end_session_endpoint | `/protocol/openid-connect/logout` |
| الگوریتم امضا | RS256 (کلید RSA، kid=`5FXTDzOlGnN2GEDj`) |
| grant_type | authorization_code + refresh_token |
| PKCE | S256 پشتیبانی می‌شود |
| token_endpoint_auth | client_secret_post / client_secret_basic / none |
| claims | sub, iss, aud, exp, iat, name, preferred_username, email, sid, resource_access |

## ۲. Backend — اعتبارسنجی توکن

`app/core/security.py`:

1. Discovery با کش ۱ ساعت؛ کنترل مطابقت `issuer` با پیکربندی.
2. JWKS با `PyJWKClient` (کش کلیدها، refresh روی kid ناشناخته).
3. `jwt.decode`: الگوریتم محدود به RS256، issuer دقیق، انقضا (leeway=۶۰s)، audience فقط اگر `OIDC_AUDIENCE` تنظیم شده باشد.
4. نقش‌ها از claims: `core_roles`, `roles`, `realm_access.roles`, `resource_access.<client>.roles` — تلاقی با نقش‌های منطقی هسته.

**نقش‌های منطقی هسته** (نگاشت به claimهای SSO): `viewer`, `master_data_editor`, `steward`, `integration_admin`, `auditor`, `tenant_admin`. مدیریت سراسری نقش‌های همه زیرسامانه‌ها در دامنه هسته نیست.

**سرویس‌به‌سرویس:** اگر claim `actor_type=service` یا `token_type=service` باشد، هویت سرویس با `client_id`/`azp` و scopes به شکل `owner:<entity>`, `read:<entity>`, `sync` در نظر گرفته می‌شود.

## ۳. مشتری (tenant) از توکن

- claimهای پذیرفته: `tenants` (لیست) یا `tenant`/`tenant_code`.
- هدر `X-Tenant-Code` به‌تنهایی معتبر نیست؛ باید با عضویت اعلامی توکن تطبیق داده شود (`TENANT_FORBIDDEN` در غیر این صورت).
- تطبیق شخص بین مشتری‌های مختلف پیش‌فرض انجام نمی‌شود (بند ۷.۱).

## ۴. Frontend — ورود بدون ذخیره گذرواژه

1. `GET /api/v1/meta` → اگر `dev_mode` باشد (فقط توسعه) پنل ورود آزمایشی نمایش داده می‌شود؛ در غیر این صورت دکمه «ورود با SSO سازمانی».
2. تولید PKCE (verifier/challenge با WebCrypto) + state؛ ریدایرکت به `authorization_endpoint`.
3. مسیر `/login/callback`: کنترل state، سپس تبادل کد با PKCE از طریق `POST /api/v1/auth/token` (پروکسی سمت Backend برای اجتناب از CORS؛ در صورت تنظیم، `OIDC_CLIENT_SECRET` فقط در سرور استفاده می‌شود).
4. توکن access در localStorage نگه‌داری می‌شود و در همه درخواست‌ها `Authorization: Bearer` ارسال می‌گردد. هیچ صفحه ورود/ذخیره گذرواژه‌ای در این پروژه وجود ندارد.

## ۵. پیکربندی

```env
OIDC_ISSUER=http://188.212.96.235:8086
OIDC_AUDIENCE=            # در صورت وجود aud در توکن‌ها
OIDC_CLIENT_ID=student360-core   # client عمومی PKCE ثبت‌شده روی SSO
OIDC_CLIENT_SECRET=       # فقط اگر روش محرمانه لازم شود
DEV_AUTH=false            # در تولید هرگز true نکنید
```

## ۶. اتصال حساب به شخص (FR-04)

- جدول `identity_account_links`: یکتایی `(tenant_id, issuer, subject)` برای اتصال فعال؛ **اتصال صرفاً بر اساس ایمیل انجام نمی‌شود**.
- اعمال: `GET /identity/me` شخص متناظر حساب جاری را برمی‌گرداند؛ اتصال/قطع با نقش متولی/مدیر یکپارچگی و ثبت ممیزی.
- در حالت dev، هویت آزمایشی (`X-Dev-User` و…) فقط برای تست است و در تولید با `DEV_AUTH=false` مسدود می‌شود.

## ۷. وضعیت یکپارچگی واقعی (بررسی ۱۴۰۵/۰۸/۲۹ — v1.0.1)

### ۷.۱. ثبت‌شده در پرتال (مطابق تصویر «مدیریت سامانه‌ها»)

| فیلد | مقدار |
|---|---|
| نام سامانه | سامانه پایه پار۳۶۰ |
| کلید سامانه (appKey) | `hr` |
| Client ID در SSO | `payeh360` |
| آدرس ورود OIDC | `http://188.212.96.235:8094/` |
| ترتیب / وضعیت | ۲ / فعال |

### ۷.۲. نقش دسترسی اکوسیستم

قرارداد مشترک سایر سامانه‌ها (`maharatyar.access`، `daneshjo360.access`) → برای این سامانه: **`hr.access`**.
در `build_actor_from_claims`: کاربر سازمانی با نقش `hr.access` (یا `payeh360.access`/`payehyar.access`) حداقل نقش `viewer` می‌گیرد؛ اگر claim مشتری نداشته باشد، مشتری پیش‌فرض `SSO_DEFAULT_TENANT` (`demo`) تخصیص می‌یابد.

### ۷.۳. ورود یک‌کلیکی سراسری (قرارداد سایر سامانه‌ها: `login_url`)

| مسیر | نقش |
|---|---|
| `GET /api/v1/auth/sso/config` | پیکربندی عمومی SSO این سامانه (issuer، client_id، login_url، redirect_uri) |
| `GET /api/v1/auth/sso/login` | نقطه شروع جریان OIDC — state/verifier در کوکی HttpOnly، ریدایرکت به IdP |
| `GET /api/v1/auth/sso/callback` | تبادل کد سمت سرور و بازگشت توکن به SPA با fragment (`/#auth=<JWT>`) |

بنابراین آدرس توصیه‌شده برای فیلد «ورود OIDC» در پرتال: `http://188.212.96.235:8094/api/v1/auth/sso/login` (ورود یک‌کلیکی از کاشی پرتال). جریان فرانت با PKCE روی `/login/callback` نیز همچنان فعال است.

### ۷.۴. اقدام باقی‌مانده در سمت IdP (پرتال 8086)

بررسی زنده (`/protocol/openid-connect/auth`) نشان داد رجیستری کلاینت‌های IdP با جدول «مدیریت سامانه‌ها»ی پرتال یکی نیست:

- `barnamehyar360` در IdP موجود است و redirect ثبت‌شده آن `http://188.212.96.235:8083/api/auth/sso/callback` است (تأیید شد؛ جریان کامل با PKCE به فرم ورود می‌رسد).
- `payeh360` (و `finance-app` و `daneshjo360`) با پیام «کلاینت ناشناس — در سامانه ثبت نشده است» رد می‌شوند.

**اقدام لازم:** در پرتال دانشجویار۳۶۰، ردیف «سامانه پایه پار۳۶۰» را ویرایش و «ذخیرهٔ تغییرات» شود تا کلاینت OIDC واقعی با این مقادیر ساخته شود:

- Client ID: `payeh360`
- redirect URI ثبت‌شده: `http://188.212.96.235:8094/api/v1/auth/sso/callback` (الگوی قرارداد: `{base}/api/v1/auth/sso/callback`)
- آدرس ورود OIDC: `http://188.212.96.235:8094/api/v1/auth/sso/login`

تا پیش از این ثبت، ورود SSO با پیام IdP مواجه می‌شود؛ سایر مسیرها (حالت dev، جریان PKCE پس از ثبت) آماده و آزمون‌شده است.
