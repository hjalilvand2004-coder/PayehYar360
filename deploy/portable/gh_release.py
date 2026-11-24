"""ساخت GitHub Release v1.0.7 و آپلود بسته‌های پرتیبل.

توکن از متغیر محیطی GH_TOKEN خوانده می‌شود (هرگز در فایل ذخیره نمی‌شود).
"""
from __future__ import annotations

import os
import sys

import httpx

OWNER = "hjalilvand2004-coder"
REPO = "PayehYar360"
TAG = "v1.0.12"
API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"

ASSETS = [
    ("/tmp/portable/PayehYar360-Portable-Windows-v1.0.12.zip", "application/zip"),
    ("/tmp/portable/PayehYar360-Portable-Linux-v1.0.12.zip", "application/zip"),
]

BODY = """## PayehYar360 — هسته مشترک و اطلاعات پایه دانشجو۳۶۰ | نسخه **v1.0.12**

> **v1.0.12 — سازماندهی زنجیره درس**: درس‌های یکتا (۸۴ رکورد واقعی درس‌یار۳۶۰) در صفحه و فرم مستقل + درس‌های تفکیکی (۱۴۳ رکورد) و اتصال کامل «درس یکتا ← درس تفکیکی (۱ تا ۳) ← سرفصل مصوب» با ایمپورت idempotent از درس‌یار۳۶۰ و ۴ بررسی کیفیت جدید.

### ۱) زنجیره درس: درس‌های یکتا و درس‌های تفکیکی — جدید در v1.0.12
- دو صفحه و فرم مستقل جدید: «درس‌های یکتا» (رأس زنجیره — کد یکتا عیناً از درس‌یار۳۶۰) و «درس‌های تفکیکی» (نمونه‌های اجرایی با سال/مجموعه)
- داده واقعی واکشی‌شده از `darsyar360.ir/admin/courses`: **۸۴ درس یکتا** و **۱۴۳ درس تفکیکی** (۵۱ رکورد سال ۱۳۹۴، ۵۷ رکورد سال ۱۴۰۳، ۳۵ ناپیوسته) — seed خودکار در اولین اجرا
- قاعده کسب‌وکار تضمین‌شده: هر درس یکتا ۱ تا ۳ درس تفکیکی دارد و هر تفکیکی سرفصل‌های مصوب خودش را (شمارش زنجیره در هر دو صفحه + نشان سلامت)
- ایمپورت idempotent: `POST /api/v1/masterdata/import/darsyar-courses` — رکورد تکراری بروزرسانی می‌شود و سرفصل‌های هم‌عنوان خودکار به تفکیکی مناسب متصل می‌شوند (در اجرای اول ۵۷ سرفصل متصل شد)
- سرفصل‌ها به زنجیره متصل شدند: فیلتر تفکیکی، نمایش زنجیره در جزئیات، انتخاب «درس تفکیکی» در فرم ویرایش سرفصل + اتصال مجدد خودکار (`POST /masterdata/syllabi/auto-link`)
- ۴ بررسی کیفیت جدید در حوزه «زنجیره درس»: درس یکتای بدون تفکیکی، تعداد تفکیکی خارج از ۱/۳، تفکیکی بدون سرفصل، سرفصل بی‌پیوند
- دامنه‌های سرویس جدید برای مصرف‌کننده‌ها: `unique-courses` (از جدول اختصاصی) و `split-courses`
- ۱۴ مسیر API جدید با نقش‌بندی کامل (خواندن: steward/admin/editor/auditor — نوشتن: steward/admin/editor — حذف: steward/admin)

### ۲) ویرایش سرفصل‌ها از پنل — v1.0.11
- مسیر جدید: `PATCH /api/v1/masterdata/syllabi/{id}` (نقش‌های steward/tenant_admin/master_data_editor)
- ویرایش همه فیلدها: عناوین، کد/نوع درس، واحد و ساعت نظری/عملی، پیش‌نیاز/هم‌نیاز، هدف کلی، ارزشیابی، منابع
- ویرایشگر ریز محتوا: افزودن، جابه‌جایی ترتیب، حذف و ساعت هر بند — ذخیره در سابقه ممیزی + updated_at برای همگام‌سازی دلتایی
- ویرایش دستی سند اسکن‌شده، برچسب «اسکن بدون متن» را برمی‌دارد
- دکمه «ویرایش» فقط برای نقش‌های مجاز در مودال جزئیات نمایش داده می‌شود

### ۳) مجموعه ۱۳۹۴ با OCR فارسی کامل شد — v1.0.10
- هر ۸۹ سند اسکن‌شده ۱۳۹۴ با tesseract (fas+eng) در ~۳۰۰dpi بازخوانی شد؛ پارس قالب وزارت علوم ۹۴:
  عنوان فارسی/انگلیسی، شماره درس اصلی، رشته و تعداد واحد، پیش‌نیاز/هم‌نیاز و مطالب پیش‌نیاز، اهداف درس، نتایج درس، **فهرست مطالب (سرفصل‌های شماره‌دار)**، کتاب‌های مرجع و نرم‌افزارهای مورد نیاز
- seed داخل بسته‌ها خودکار ارتقا می‌یابد: نصب‌های موجود v1.0.9 (با رکوردهای ناقص ۱۳۹۴) در اولین اجرا با نسخه کامل OCR بازنویسی می‌شوند — بدون دست‌کاری دستی

### ۴) حذف یک مجموعه + ایمپورت مجدد
- مسیر جدید: `DELETE /api/v1/masterdata/syllabi/set/{source_set}` (نقش steward/tenant_admin) — حذف کامل سندها و سرفصل‌های یک مجموعه با ثبت در تاریخچه
- دکمه «حذف مجموعه» در صفحه سرفصل دروس با تأیید دومرحله‌ای — برای ایمپورت مجدد نسخه کامل

### ۵) ارزیابی کیفیت داده سرفصل‌ها — حوزه «سرفصل دروس» در داشبورد کیفیت
- ۸ بررسی: سند اسکن‌شده بدون متن (پوشش)، عنوان فارسی خالی، کد درس خالی، واحد/ساعت نامشخص، درس بدون سرفصل/ریز محتوا (بحرانی)، بدون هدف کلی، عنوان تکراری در مجموعه، کد تکراری در مجموعه
- هر بررسی با drill-down تا ردیف متأثر (شناسه، عنوان، مجموعه) + امتیاز وزنی در امتیاز کل کیفیت

### ۶) ماژول «سرفصل دروس» — پایه (v1.0.9)
- سه مجموعه سرفصل مصوب ثبت شد: **مصوب ۱۳۹۴** (۸۹ درس — اسناد اسکن‌شده، کاتالوگ از نام فایل)،
  **مصوب سری ۴۰۳ مهندسی کامپیوتر (CE403)** (۷۱ درس با پارس کامل)، **مصوب ۱۴۰۰ (NP1400)** (۳۵ درس با پارس کامل)
- در مجموع ~۲٬۹۵۰ ریز محتوا با ساعت نظری/عملی (جایی که سند دارد)، هدف کلی، نوع/واحد/ساعت، پیش‌نیاز و هم‌نیاز، روش ارزشیابی و منابع
- صفحه جدید «سرفصل دروس» در پنل: فیلتر بر اساس مجموعه، جست‌وجو در عنوان/کد، جزئیات کامل هر درس، راهنمای صفحه
- جدول‌های جدید: `md_course_syllabi` + `md_course_syllabus_topics` (مهاجرت 0003)
- ایمپورت idempotent: یکتایی بر (مجموعه + فایل منبع)؛ ایمپورت مجدد همان فایل بروزرسانی می‌کند
- متن کامل اسناد متنی در `raw_text` حفظ شده تا هیچ محتوایی از دست نرود؛ اسناد اسکن‌شده با پرچم `has_text=false` برای OCR بعدی

### ۷) مصرف در سایر سامانه‌ها
- دامنه جدید سرویس اطلاعات پایه: `GET /api/v1/services/masterdata/course-syllabi` با هدر `X-API-Key`
- پاسخ شامل `units` و `hours` (نظری/عملی)، آرایه کامل `topics` و `updated_at` برای همگام‌سازی دلتایی با `since`
- هر واکشی در تاریخچه (`course-syllabi`) با زمان شمسی ثبت می‌شود؛ کاتالوگ سرویس‌ها شمارش دامنه جدید را نشان می‌دهد

### ۸) امکانات نسخه‌های قبلی (v1.0.7–1.0.11)
- سرویس‌دهی اطلاعات پایه: اساتید، کلاس‌ها/سالن‌ها، درس‌های یکتا، آیتم‌های مرجع + دلتا (`since`) + تاریخچه شمسی
- رفع باگ SSO (redirect_uri callback) و بسته پرتیبل ویندوز (annotated-doc) در v1.0.8
- پیکربندی کامل استقرار روی **http://188.212.96.235:8094/** — redirect URI کلاینت `payeh360`: `http://188.212.96.235:8094/api/v1/auth/sso/callback`

### بسته‌های پرتیبل (بدون نیاز به نصب Python یا PyCharm)
| فایل | سیستم | اجرا |
|---|---|---|
| `PayehYar360-Portable-Windows-v1.0.12.zip` | ویندوز ۶۴بیتی | استخراج → اجرای `start.bat` (پنجره خطا باز می‌ماند) |
| `PayehYar360-Portable-Linux-v1.0.12.zip` | لینوکس x86_64 | استخراج → `chmod +x payehyar360-server && ./payehyar360-server` |

> سرفصل‌ها داخل هر دو بسته از قبل ایمپورت‌شده‌اند (seed) — صفحه «سرفصل دروس» بلافاصله کار می‌کند.
> ورود آزمایشی پرتیبل (پیش‌فرض): مشتری `demo`، کاربر `steward1`، نقش `steward` — روی `http://localhost:8094`
"""


def main() -> int:
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("GH_TOKEN تنظیم نشده است")
        return 1
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}

    with httpx.Client(timeout=30, headers=headers) as c:
        existing = c.get(f"{API}/repos/{OWNER}/{REPO}/releases/tags/{TAG}")
        if existing.status_code == 200:
            rel = existing.json()
            print(f"release existed: id={rel['id']}")
        else:
            r = c.post(f"{API}/repos/{OWNER}/{REPO}/releases", json={
                "tag_name": TAG,
                "target_commitish": "main",
                "name": "نسخه ۱.۰.۱۲ — ماژول سرفصل دروس (۱۹۵ سند مصوب / ~۲۹۵۰ ریز محتوا) + سرویس course-syllabi",
                "body": BODY,
                "draft": False,
                "prerelease": False,
            })
            r.raise_for_status()
            rel = r.json()
            print(f"release created: id={rel['id']}")

        rel_id = rel["id"]
        existing_assets = {a["name"] for a in c.get(f"{API}/repos/{OWNER}/{REPO}/releases/{rel_id}/assets").json()}
        for path, ctype in ASSETS:
            name = os.path.basename(path)
            size = os.path.getsize(path)
            if name in existing_assets:
                print(f"skip (exists): {name}")
                continue
            print(f"uploading {name} ({size/1e6:.1f} MB) ...", flush=True)
            with open(path, "rb") as fh:
                r = c.post(
                    f"{UPLOAD}/repos/{OWNER}/{REPO}/releases/{rel_id}/assets",
                    params={"name": name},
                    content=fh,
                    headers={"Content-Type": ctype, "Content-Length": str(size)},
                    timeout=httpx.Timeout(600, connect=30),
                )
            r.raise_for_status()
            print(f"uploaded: {name} -> {r.json()['browser_download_url']}")
        print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
