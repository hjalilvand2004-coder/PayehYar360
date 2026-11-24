# ابزار ساخت و انتشار بسته‌های پرتیبل

اسکریپت‌های ساخت بسته‌های پرتیبل ویندوز/لینوکس و انتشار آن‌ها در GitHub Release.
(این اسکریپت‌ها در سندباکس ساخت اجرا می‌شوند؛ مسیرهای `/tmp/portable` و
`/home/z/my-project` بسته به محیط قابل تغییرند.)

## جریان ساخت
1. `build_win_wheels.py` — زنجیره کامل وابستگی‌های runtime با BFS روی
   importlib.metadata محیطِ آزم‌شده (بدون لیست دستی) و دانلود ویل‌های win_amd64.
2. `download_win_wheels.py` — دانلود ویل‌ها با لیست pin نسخه‌های محیط آزم‌شده
   (روش مکمل؛ نسخه‌ها باید با `pip freeze` محیط آزمون‌ها یکی باشد).
3. `check_win_wheels_closure.py` — چکر بستار وابستگی‌ها از روی METADATA خود ویل‌ها
   با ارزیابی مارکرهای ویندوز/Py3.12؛ هر وابستگیِ لازمِ بدون ویل → خطا.
4. `build_portable_windows.py` / `build_portable_linux.py` — مونتاژ بسته:
   پایتون embeddable + ویل‌ها در Lib/site-packages + کد backend + frontend/dist +
   start.bat، سپس zip.
5. `upload_release_assets.sh` / `update_release_body.py` / `gh_release.py` —
   انتشار assetها و یادداشت‌ها در GitHub Release.

## درس تاریخی v1.0.13 (نوامبر ۲۰۲۶)
در بسته ویندوز اولیه، ویل `annotated-doc==0.0.4` (وابستگی اجباری
`fastapi>=0.126`) جا افتاده بود و هنگام استارت
`ModuleNotFoundError: No module named 'annotated_doc'` می‌داد؛ ویل `tzdata`
(لازم psycopg روی ویندوز) هم نبود. بسته‌های اصلاح‌شده در Release v1.0.13
جایگزین شدند و چکر بستار (گام ۳) برای جلوگیری از تکرار این خطا اضافه شد.

## توکن
اسکریپت‌های انتشار توکن را فقط از متغیر محیطی `GH_TOKEN` می‌خوانند —
هرگز در فایل یا آرگومان هاردکد نکنید.
