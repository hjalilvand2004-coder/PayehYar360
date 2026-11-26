# 08 — قرارداد همگام‌سازی دانشجویان با دانشگاه هوشمند (فضایار۳۶۰ — پورت 8095)

> وضعیت: نسخه 1.0 نسخه‌بندی‌شده — هم‌راستا با پایه‌یار۳۶۰ v1.0.16
> طرف اول: پایه‌یار۳۶۰ (هسته مشترک و اطلاعات پایه — پورت 8094)
> طرف دوم: دانشگاه هوشمند / فضایار۳۶۰ (مدیریت فضاهای آموزشی — پورت 8095)

## ۱) هدف و چرخه داده

دانشجو بازیگر اصلی اکوسیستم دانشجویار۳۶۰ است. پایه‌یار۳۶۰ به‌عنوان **هسته اطلاعات پایه**،
رجیستری دانشجویان را نگه می‌دارد و با «هماهنگی کامل» از سامانه دانشگاه هوشمند تغذیه می‌شود.
هماهنگی به **دو جهت** طراحی شده تا تیم فضایار بسته به معماری خود یکی را برگزیند (یا هر دو را):

| جهت | مکانیزم | طرف آغازگر | endpoint |
|---|---|---|---|
| Pull (واکشی) | پایه‌یار از فضایار می‌خواند | پایه‌یار۳۶۰ | `GET {SMART_UNI_BASE_URL}/api/v1/students` |
| Push (ارسال) | فضایار به پایه‌یار می‌فرستد | فضایار۳۶۰ | `POST /api/v1/students/ingest` (روی پایه‌یار) |

هر دو جهت از **یک نگاشت مشترک** استفاده می‌کنند؛ نتیجه هر دو idempotent است — ارسال مجدد همان
رکورد بدون تغییر، هیچ اثر جانبی ندارد (فقط meta سینک به‌روز می‌شود).

## ۲) قرارداد pull — آنچه پایه‌یار از فضایار می‌خواند

```
GET http://188.212.96.235:8095/api/v1/students?limit=200&offset=0
X-API-Key: <اختیاری — از متغیر SMART_UNI_API_KEY سمت پایه‌یار>
```

پاسخ مورد انتظار (JSON):

```json
{
  "total": 2,
  "items": [
    {
      "external_ref": "su-1001",
      "student_number": "403997001",
      "national_id": "0023456789",
      "first_name": "حسین",
      "last_name": "کریمی",
      "father_name": "رضا",
      "gender": "male",
      "birth_date": "1383-02-15",
      "mobile": "09351112233",
      "phone": "",
      "email": "",
      "city": "مشهد",
      "province": "خراسان رضوی",
      "university_code": "u01",
      "university_name": "دانشگاه فردوسی مشهد",
      "major_code": "ee-01",
      "major_name": "مهندسی برق",
      "degree_level": "کارشناسی ارشد",
      "entrance_year": 1403,
      "status": "در حال تحصیل"
    }
  ]
}
```

- صفحه‌بندی: پایه‌یار تا رسیدن به `total` با گام 200 ادامه می‌دهد؛ اگر فضایار صفحه‌بندی ندارد،
  `total` را برابر طول آرایه بفرستد.
- اگر هنوز endpoint در فضایار فعال نشده، پایه‌یار خطا را **گزارش می‌کند و رکوردهای موجود را
  دست‌نخورده نگه می‌دارد** — سینک هرگز باعث از دست رفتن داده نمی‌شود.

## ۳) قرارداد push — آنچه فضایار به پایه‌یار می‌فرستد

```
POST http://188.212.96.235:8094/api/v1/students/ingest
X-Api-Key: <STUDENTS_INGEST_KEY پایه‌یار — از متغیر محیطی>
X-Tenant-Code: demo
Content-Type: application/json

{"items": [ { ...همان ساختار بخش ۲... } ]}
```

پاسخ: همان گزارش سینک (`batch_id`, `created`, `updated`, `unchanged`, `skipped`, `message`).

- کلید از متغیر `STUDENTS_INGEST_KEY` سمت پایه‌یار تنظیم می‌شود؛ اگر تنظیم نشده باشد پاسخ 503
  با کد `INGEST_DISABLED` برمی‌گردد.
- این مسیر احراز کاربر نمی‌خواهد (سرویس‌به‌سرویس) و در ممیزی با هویت `service:smart-university`
  ثبت می‌شود.

## ۴) نگاشت فیلدها (مبدأ فضایار → هسته پایه‌یار)

| فیلد مبدأ | فیلد هسته | الزام | توضیح |
|---|---|---|---|
| `external_ref` | `ext_ref` | توصیه‌شده | کلید تطبیق اولویت اول |
| `student_number` | `student_number` | الزام* | یکتا در هر مشتری؛ کلید تطبیق سوم |
| `national_id` | `national_id` | توصیه‌شده | کلید تطبیق دوم؛ 10 رقم |
| `first_name` / `last_name` | `first_name` / `last_name` | الزام | |
| `father_name`, `gender`, `birth_date` | هم‌نام | اختیاری | gender: `male/female` |
| `mobile` | `mobile` | الزام* | یک‌ساز خودکار: `+98`/`0098`/فاصله → `09xxxxxxxxx` |
| `phone`, `email` | هم‌نام | اختیاری | |
| `city` | `city` | الزام* | شهر محل سکونت |
| `province` | `province` | اختیاری | |
| `university_name` (+`university_code`) | `university_name` / `university_code` | الزام* | اگر فقط `university` بفرستد هم پذیرفته می‌شود |
| `major_name` (+`major_code`) | `major_name` / `major_code` | الزام* | معادل‌های `major`، `field_of_study` هم پذیرفته می‌شود |
| `degree_level` | `degree_level` | الزام* | **کد کانونی یا برچسب فارسی** — جدول بخش ۵ |
| `entrance_year` | `entrance_year` | اختیاری | عدد شمسی |
| `status` | `status` | اختیاری | «در حال تحصیل»→`active`، «فارغ‌التحصیل»→`graduated`، «انصراف»→`withdrawn`، «تعلیق»→`suspended` |

*اگر الزامی مفقود باشد رکورد **نادیده** و با دلیل در `skipped` گزارش می‌شود — کل batch نمی‌شکند.

## ۵) کدهای کانونی مقطع تحصیلی

| کد کانونی (ذخیره در هسته) | برچسب فارسی | مترادف‌های پذیرفته‌شده در ورودی |
|---|---|---|
| `kardani` | کاردانی | کاردانی، associate |
| `karshenasi` | کارشناسی | کارشناسی، کارشناسی پیوسته، bachelor |
| `karshenasi_arshad` | کارشناسی ارشد | کارشناسی ارشد، ارشد، کارشناسی ناپیوسته، master |
| `doktori_herfei` | دکتری حرفه‌ای | دکترای حرفه‌ای، professional_doctorate |
| `doktori_takhassosi` | دکتری تخصصی | دکتری، phd، doctorate |
| `post_doktori` | پسادکتری | پست‌دکتری، postdoc |

مقدار ناشناخته عیناً ذخیره می‌شود تا داده از دست نرود؛ در گزارش کیفیت قابل رصد است.

## ۶) قواعد تطبیق و یکتایی (سمت پایه‌یار)

1. تطبیق رکورد مبدأ با رکورد هسته به ترتیب: `ext_ref` → `national_id` → `student_number`.
2. شماره دانشجویی در هر مشتری (tenant) یکتاست؛ تلاش برای ساخت رکورد تکراری → `skipped`.
3. رکوردهای دستی با سینک مبدأ به‌روزرسانی می‌شوند (منشأ به `smart_university` تغییر می‌کند) —
   این تصمیم عمداً است: سامانه مبدأ «مرجع» دانشجوست؛ ثبت دستی نقش مکمل/سریع را دارد.
4. هر تغییر در change_log + audit ثبت و رویداد `StudentCreated/Updated/Deactivated` به Outbox
   می‌رود تا سایر سامانه‌های اکوسیستم با همگام‌سازی دلتایی بگیرند.
5. سینک meta (`synced_at`, `sync_batch`) در تشخیص «بدون تغییر» لحاظ نمی‌شود.

## ۷) تنظیمات پایه‌یار (متغیرهای محیطی)

| متغیر | پیش‌فرض | توضیح |
|---|---|---|
| `SMART_UNI_BASE_URL` | `http://188.212.96.235:8095` | ریشه سامانه دانشگاه هوشمند |
| `SMART_UNI_STUDENTS_PATH` | `/api/v1/students` | مسیر قرارداد pull |
| `SMART_UNI_API_KEY` | خالی | اگر فضایار خواندن را با کلید محافظت کرد |
| `STUDENTS_INGEST_KEY` | خالی | کلید push سمت پایه‌یار؛ خالی = ingest غیرفعال (503) |
| `EXTERNAL_HTTP_TIMEOUT` | `20.0` | مهلت تماس pull (ثانیه) |

## ۸) کد نمونه برای تیم فضایار (push)

```python
import httpx

items = [
    {
        "external_ref": "su-1001", "student_number": "403997001",
        "national_id": "0023456789", "first_name": "حسین", "last_name": "کریمی",
        "mobile": "09351112233", "city": "مشهد",
        "university_name": "دانشگاه فردوسی مشهد", "major_name": "مهندسی برق",
        "degree_level": "کارشناسی ارشد", "entrance_year": 1403, "status": "در حال تحصیل",
    },
]
r = httpx.post(
    "http://188.212.96.235:8094/api/v1/students/ingest",
    headers={"X-Api-Key": "...", "X-Tenant-Code": "demo"},
    json={"items": items}, timeout=30,
)
print(r.status_code, r.json())   # 200 {"batch_id": ..., "created": 1, ...}
```

## ۹) راستی‌آزمایی دوطرفه پس از فعال‌سازی

```bash
# سمت پایه‌یار — گزارش pull:
curl -s -X POST http://localhost:8094/api/v1/students/sync \
  -H "X-Dev-User: steward1" -H "X-Dev-Roles: steward" -H "X-Dev-Tenants: demo" -H "Authorization: Bearer dev"

# سمت فضایار — وجود endpoint قرارداد:
curl -s "http://188.212.96.235:8095/api/v1/students?limit=1" -H "X-API-Key: ..." | head -c 500
```
