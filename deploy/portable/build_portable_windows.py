"""ساخت بسته پرتیبل Windows — پایتون embeddable + ویل‌های win_amd64 + کد و فرانت."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

ROOT = Path("/tmp/portable")
OUT = ROOT / "build" / "PayehYar360-Portable-Windows"
PROJECT = Path("/home/z/my-project/download/student360-shared-core")
PY_EMBED = ROOT / "python-embed.zip"
WHEELS = ROOT / "wheels"

PTH_CONTENT = """python312.zip
.
Lib/site-packages
..
import site
"""

START_BAT = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "ROOTF=%ROOT:\=/%"

set "PORT=8094"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "DATABASE_URL=sqlite:///%ROOTF%/data/core.db"
set "DATA_DIR=%ROOT%\data"
set "SERVE_FRONTEND_DIR=%ROOT%\frontend\dist"
set "AUTO_CREATE_TABLES=true"
set "SEED_DEMO=true"
set "WORKERS_IN_PROCESS=true"
set "DEV_AUTH=true"
set "ALLOWED_ORIGINS=http://188.212.96.235:8094,http://localhost:8094,http://127.0.0.1:8094,http://188.212.96.235:8084,http://127.0.0.1:8084,http://localhost:8084"

if not exist "%ROOT%\data" mkdir "%ROOT%\data"

echo ==========================================================
echo   PayehYar360 - Shared Core ^& Master Data (portable v1.0.16)
echo   Panel ^& API : http://localhost:8094
echo   Swagger     : http://localhost:8094/docs
echo   Login demo  : user=steward1  roles=steward,tenant_admin  tenant=demo
echo   Stop        : close this window (Ctrl+C)
echo ==========================================================

rem --- پیش‌بررسی کتابخانه‌ها: اگر ماژولی نباشد، پیام دقیق بالا نمایش داده می‌شود و پنجره باز می‌ماند
"python\python.exe" -X utf8 -c "import fastapi,uvicorn,sqlalchemy,pydantic,pydantic_settings,jwt,cryptography,pika,httpx,alembic,anyio,greenlet,httpcore,typing_extensions,mako,annotated_doc"
if errorlevel 1 (
  echo.
  echo [خطا] یکی از کتابخانه‌ها بارگذاری نشد — متن خطای بالا را برای پشتیبانی ارسال کنید.
  pause
  exit /b 1
)

rem --- مرورگر بعد از ۴ ثانیه باز می‌شود؛ اگر سرور بالا نیامد، پیام خطا در همین پنجره می‌ماند
start "" cmd /c "timeout /t 4 >nul & start http://localhost:8094"
"python\python.exe" -X utf8 -m uvicorn app.main:app --host 0.0.0.0 --port %PORT%
if errorlevel 1 (
  echo.
  echo [خطا] اجرای سرور ناموفق بود — متن خطای بالا را برای پشتیبانی ارسال کنید.
  echo نکته: اگر پیام مربوط به bind/port است، پورت 8094 روی سیستم اشغال است؛ PORT را در همین فایل تغییر دهید.
)
echo.
echo پایان اجرا — با کلیدی پنجره را ببندید.
pause
endlocal
"""

README = """# PayehYar360 — نسخه پرتیبل Windows (v1.0.16)

اجرا روی هر ویندوز ۶۴بیتی **بدون نصب Python یا PyCharm** — پایتون و همه وابستگی‌ها داخل همین پوشه است.

## تازه‌های v1.0.16 — بخش ویژه دانشجویان + هماهنگی با دانشگاه هوشمند
- **رجیستری دانشجویان:** ثبت و مدیریت کامل دانشجویان — مشخصات هویتی، شماره تلفن همراه، شهر محل سکونت، دانشگاه، رشته تحصیلی و **مقطع تحصیلی** — با کنترل نسخه (If-Match)، ممیزی کامل و فیلترهای اختصاصی (مقطع/دانشگاه/شهر/وضعیت/منشأ).
- **هماهنگی کامل با فضایار۳۶۰ (دانشگاه هوشمند — پورت 8095):** سینک دوسویه — pull از `GET /api/v1/students` فضایار و push با کلید API به `POST /api/v1/students/ingest` پایه‌یار؛ قرارداد کامل و نمونه کد: `docs/08-students-integration.md`.
- **نگاشت هوشمند مقاطع:** برچسب فارسی (کارشناسی ارشد، دکتری و…) ↔ کد کانونی؛ تطبیق رکورد با اولویت ext_ref ← کد ملی ← شماره دانشجویی؛ گزارش کامل ایجاد/به‌روزرسانی/نادیده بعد از هر سینک.
- تست‌ها: ۵۳/۵۳ سبز (۱۵ آزمون جدید دانشجو).

## تغییرات v1.0.15 — تم «Aurora Premium»
- بازطراحی شیشه‌ای پنل با گرادیان آرورا + حالت شب/روز با دکمه «تغییر تم» و فونت وزیرمتن self-host.

## تغییرات v1.0.14 (رفع کامل وابستگی‌های بسته)
- **رفع ModuleNotFoundError استارت:** ویل `annotated-doc==0.0.4` (وابستگی اجباری FastAPI 0.128) که در بسته v1.0.13 جا افتاده بود اضافه شد — start.bat اکنون بدون خطا بالا می‌آید.
- **tzdata==2026.1:** برای اتصال PostgreSQL روی ویندوز (psycopg).
- چکر بستار وابستگی‌ها در مخزن: `deploy/portable/check_win_wheels_closure.py`.

## تغییرات v1.0.13 (رفع مشکل واکشی دانشجو۳۶۰/یادگیری هوشمند)
- **رفع باگ 500 در واکشی split-courses** (NameError ترتیب‌دهی در v1.0.12).
- **ETag/304:** پاسخ `/api/v1/services/masterdata/{domain}` هدر ETag دارد؛ `If-None-Match` با داده بدون تغییر → 304.
- **نام جایگزین `syllabi`:** معادل `course-syllabi` (پاسخ با requested_domain).
- **CORS:** مبداهای سامانه یادگیری هوشمند (پورت 8084) اضافه شد و ETag در expose_headers است.

## اجرا
1. کل پوشه را در یک مسیر بدون فاصله/فارسی استخراج کنید (مثلاً `C:\\PayehYar360`).
2. `start.bat` را اجرا کنید → مرورگر روی `http://localhost:8094` باز می‌شود.
3. در پنل ورود آزمایشی: مشتری `demo`، کاربر `steward1`، نقش‌ها `steward` + `tenant_admin`.

## نکات
- داده در پوشه `data\\` (SQLite + Snapshot) ساخته می‌شود؛ برای پاک‌سازی کامل، فقط `data` را حذف کنید.
- اتصال به SSO واقعی و PostgreSQL: متغیرهای محیطی مطابق `docs/07-deployment.md` (در مخزن) تنظیم یا از Docker استفاده کنید.
- ورود یکپارچه SSO (پرتال دانشجویار۳۶۰): تنظیمات پیش‌فرض به issuer=188.212.96.235:8086 و client=payeh360 اشاره می‌کند؛ در این حالت پرتیبل `DEV_AUTH=true` دارد و ورود آزمایشی فعال است.
- این بسته برای توسعه/پایلوت است؛ استقرار تولیدی: `deploy/docker-compose.yml`.
- پورت پیش‌فرض ۸۰۹۴؛ با ویرایش `start.bat` تغییر دهید.

## استقرار روی سرور سازمانی (188.212.96.235 — پورت 8094)
- در فایروال ویندوز سرور، پورت ۸۰۹۴ را برای ورودی باز کنید (-admin):
  `netsh advfirewall firewall add rule name="PayehYar360" dir=in action=allow protocol=TCP localport=8094`
- برای ورود یکپارچه سازمانی (بدون ورود آزمایشی)، قبل از اجرا این متغیرها را در `start.bat` تنظیم کنید:
  `DEV_AUTH=false`، `OIDC_PUBLIC_BASE_URL=http://188.212.96.235:8094`،
  `ALLOWED_ORIGINS=http://188.212.96.235:8094,http://188.212.96.235:8084,http://127.0.0.1:8084,http://localhost:8084`
- redirect URI کلاینت `payeh360` در پرتال SSO باید دقیقاً این باشد:
  `http://188.212.96.235:8094/api/v1/auth/sso/callback`
- نسخه v1.0.13: رفع باگ واکشی درس تفکیکی + ETag/304 + alias syllabi + CORS پورت 8084.

## عیب‌یابی
- پنجره ترمینال دیگر خودکار بسته نمی‌شود؛ اگر خطا رخ دهد، متن خطا در همان پنجره می‌ماند — آن را برای پشتیبانی ارسال کنید.
- «error while attempting to bind ... port 8094»: پورت اشغال است (نمونه قبلی باز است)؛ مقدار `PORT` در `start.bat` را تغییر دهید.
- «ModuleNotFoundError»: بسته ناقص استخراج شده — کل پوشه را از ابتدا استخراج کنید (کپی دستی تک‌تک فایل‌ها نکنید).
- برای اجرای مجدد با داده تمیز: پوشه `data` را حذف و `start.bat` را دوباره اجرا کنید.
"""

def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # ۱) پایتون embeddable
    py_dir = OUT / "python"
    py_dir.mkdir()
    with zipfile.ZipFile(PY_EMBED) as z:
        z.extractall(py_dir)
    (py_dir / "python312._pth").write_text(PTH_CONTENT, encoding="ascii")

    # ۲) ویل‌ها → Lib/site-packages
    sp = py_dir / "Lib" / "site-packages"
    sp.mkdir(parents=True, exist_ok=True)
    for whl in sorted(WHEELS.glob("*.whl")):
        with zipfile.ZipFile(whl) as z:
            z.extractall(sp)
    print(f"site-packages: {len(list(sp.iterdir()))} entries")

    # ۳) کد بک‌اند و فرانت
    shutil.copytree(PROJECT / "backend" / "app", OUT / "app")
    (OUT / "frontend").mkdir()
    shutil.copytree(PROJECT / "frontend" / "dist", OUT / "frontend" / "dist")

    # ۴) اسکریپت‌ها
    (OUT / "start.bat").write_text(START_BAT, encoding="utf-8", newline="\r\n")
    (OUT / "README-PORTABLE.md").write_text(README, encoding="utf-8")

    # ۵) زیپ نهایی
    out_zip = ROOT / "PayehYar360-Portable-Windows-v1.0.16.zip"
    if out_zip.exists():
        out_zip.unlink()
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(OUT.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(OUT.parent))
    print(f"OK: {out_zip} ({out_zip.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
