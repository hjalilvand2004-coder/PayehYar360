"""ساخت بسته پرتیبل Linux v1.0.16 — بیلد PyInstaller + README + zip."""
import subprocess
import shutil
import sys
from pathlib import Path

PROJECT = Path("/home/z/my-project/download/student360-shared-core")
BUILD = Path("/tmp/portable/build/PayehYar360-Portable-Linux")
BIN = PROJECT / "backend" / "dist" / "payehyar360-server"
ZIP = Path("/tmp/portable/PayehYar360-Portable-Linux-v1.0.16.zip")
PYI_WORK = Path("/tmp/portable/pyi")

README = """# PayehYar360 — نسخه پرتیبل Linux (v1.0.16)

اجرا روی هر لینوکس x86_64 **بدون نصب Python** — همه وابستگی‌ها داخل باینری است.

## تازه‌های v1.0.16 — بخش ویژه دانشجویان + هماهنگی با دانشگاه هوشمند
- **رجیستری دانشجویان:** ثبت و مدیریت کامل — هویتی، همراه، شهر محل سکونت، دانشگاه، رشته و **مقطع تحصیلی** — با کنترل نسخه و ممیزی.
- **هماهنگی کامل با فضایار۳۶۰ (پورت 8095):** سینک دوسویه (pull از `GET /api/v1/students` فضایار + push با کلید API به `POST /api/v1/students/ingest`) — قرارداد: `docs/08-students-integration.md`.
- نگاشت هوشمند مقاطع و تطبیق رکورد (ext_ref ← کد ملی ← شماره دانشجویی)؛ گزارش کامل بعد از هر سینک.
- باینری با ماژول دانشجو بازبیلد شد؛ openapi.json → 1.0.16. تست‌ها ۵۳/۵۳ سبز.

## تغییرات v1.0.15 — تم «Aurora Premium»
- بازطراحی شیشه‌ای پنل با گرادیان آرورا + حالت شب/روز با دکمه «تغییر تم».

## تغییرات v1.0.14 (هم‌ترازی نسخه)
- کد همان v1.0.13؛ ویل‌های `annotated-doc` و `tzdata` در بسته ویندوز کامل شدند.

## تغییرات v1.0.13 (رفع مشکل واکشی دانشجو۳۶۰/یادگیری هوشمند)
- **رفع باگ 500 در واکشی split-courses** (NameError ترتیب‌دهی در v1.0.12) — همگام‌سازی
  «درس‌های تفکیکی» اکنون بدون خطا کار می‌کند.
- **ETag/304:** هر پاسخ `/api/v1/services/masterdata/{domain}` هدر ETag دارد؛
  ارسال `If-None-Match` با داده بدون تغییر → 304 بدون انتقال بدنه (صرفه‌جویی پهنای باند).
- **نام جایگزین `syllabi`:** معادل `course-syllabi` (هر دو نام معتبر؛ پاسخ با requested_domain).
- **CORS:** مبداهای سامانه یادگیری هوشمند (پورت 8084) اضافه شد و ETag در expose_headers است.
- آزمون‌ها: ۳۸/۳۸ سبز (۵ آزمون جدید در backend/tests/test_service_fetch_v1013.py).

## اجرا
1. کل پوشه را استخراج کنید.
2. `chmod +x payehyar360-server && ./payehyar360-server` → پنل روی `http://localhost:8094`.
3. در پنل ورود آزمایشی: مشتری `demo`، کاربر `steward1`، نقش‌ها `steward` + `tenant_admin`.

## استقرار روی سرور سازمانی (188.212.96.235 — پورت 8094)
```bash
# پس از استخراج، در فایروال سرور پورت 8094 را باز کنید:
sudo firewall-cmd --permanent --add-port=8094/tcp && sudo firewall-cmd --reload   # RHEL/CentOS
# یا:  sudo ufw allow 8094/tcp                                                    # Ubuntu

# اجرای سرویس واقعی (ورود یکپارچه سازمانی — بدون ورود آزمایشی):
DEV_AUTH=false OIDC_CLIENT_ID=payeh360 \\
OIDC_ISSUER=http://188.212.96.235:8086 \\
OIDC_PUBLIC_BASE_URL=http://188.212.96.235:8094 \\
ALLOWED_ORIGINS=http://188.212.96.235:8094,http://188.212.96.235:8084,http://127.0.0.1:8084,http://localhost:8084 \\
./payehyar360-server
```
- redirect URI کلاینت `payeh360` در پرتال SSO باید دقیقاً این باشد:
  `http://188.212.96.235:8094/api/v1/auth/sso/callback`
- برای استقرار تولیدی کامل (PostgreSQL + RabbitMQ + workerها): `deploy/docker-compose.yml` — سند `docs/07-deployment.md`.

## راستی‌آزمایی سریع پس از استقرار
```bash
curl -s http://localhost:8094/openapi.json | grep -o '"version":"[^"]*"' | head -1   # باید 1.0.16 باشد
KEY="pyk_..."   # کلید صادرشده در پنل «سرویس‌کلاینت‌ها»
for D in unique-courses split-courses course-syllabi syllabi; do
  curl -s -o /dev/null -w "$D → %{http_code}\\n" -H "X-API-Key: $KEY" \\
    "http://localhost:8094/api/v1/services/masterdata/$D"
done
```

## نکات
- داده در پوشه `data/` (SQLite + Snapshot) ساخته می‌شود؛ برای پاک‌سازی کامل، فقط `data` را حذف کنید.
- اطلاعات پایه شامل **۱۴۳ درس یکتای واقعی** سامانه نظرسنجی دروس (8082) با فیلدهای کامل:
  کد یکتا، عنوان، گروه، ظرفیت برآوردی (قابل ثبت از پنل)، واحد نظری/عملی، وضعیت،
  پیش‌نیازهای لینک‌شده به کد درس و سال طرح‌درس (مجموعه‌های `unique_courses` و `course_sections`).
- پورت پیش‌فرض ۸۰۹۴ (PORT=8096 ./payehyar360-server).
- نسخه v1.0.13: ماژول «سرفصل دروس» — ۱۹۵ سند سرفصل مصوب (مجموعه‌های ۱۳۹۴، سری ۴۰۳ و ۱۴۰۰)
  با ~۲۹۵۰ ریز محتوا؛ مصرف سایر سامانه‌ها از دامنه course-syllabi (یا alias syllabi).
"""


def build_binary() -> None:
    """بیلد باینری با کد فعلی (v1.0.16)."""
    cmd = [
        sys.executable, "-m", "PyInstaller", "--clean", "--onefile", "--noconfirm",
        "--name", "payehyar360-server",
        "--distpath", str(BIN.parent), "--workpath", str(PYI_WORK / "work"),
        "--specpath", str(PYI_WORK / "spec"),
        "--paths", str(PROJECT / "backend"),
        "--add-data", f"{PROJECT / 'frontend' / 'dist'}:frontend_dist",
        "--add-data", f"{PROJECT / 'backend' / 'app' / 'data'}:app/data",
        # PyInstaller 6.x مقدار DEST را همیشه دایرکتوری می‌گیرد — dest=app تا فایل
        # در app/seed_darsyar_courses.json استخراج شود (نه داخل پوشه همنام)
        "--add-data", f"{PROJECT / 'backend' / 'app' / 'seed_darsyar_courses.json'}:app",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.http.h11_impl",
        "--hidden-import", "uvicorn.protocols.http.httptools_impl",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.protocols.websockets.websockets_impl",
        "--hidden-import", "uvicorn.protocols.websockets.wsproto_impl",
        "--hidden-import", "uvicorn.lifespan.on",
        str(PROJECT / "backend" / "run_portable.py"),
    ]
    subprocess.run(cmd, cwd=str(PROJECT), check=True)


def main() -> None:
    build_binary()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)
    shutil.copy2(BIN, BUILD / "payehyar360-server")
    (BUILD / "README-PORTABLE.md").write_text(README, encoding="utf-8")
    if ZIP.exists():
        ZIP.unlink()
    subprocess.run(["zip", "-qr9", str(ZIP), BUILD.name], cwd=str(BUILD.parent), check=True)
    print(f"OK: {ZIP} ({ZIP.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
