"""دانلود ویل‌های win_amd64 برای بسته پرتیبل ویندوز — نسخه‌های دقیق محیطِ آزم‌شده.

قاعده: هر بسته فقط یک نسخه (بدون تکرار pin متفاوت) تا ویل‌های تداخل‌دار مثل
cryptography-45 + cryptography-50 هر دو داخل بسته نروند.
لیست pinها باید با `python3 -m pip freeze` محیطی که آزمون‌ها در آن پاس می‌شود همخوان باشد.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WHEELS = Path("/tmp/portable/wheels")

# نسخه‌های محیط آزم‌شده (کامیت v1.0.7) — psycopg-binary هم‌نسخه psycopg؛
# sniffio/typing-extensions/colorama وابستگی‌های anyio/uvicorn/click روی ویندوز
# annotated-doc: وابستگی اجباری fastapi>=0.126 — جا افتادن آن یعنی ModuleNotFoundError در استارت
# (باگ واقعی بسته ویندوز v1.0.13 روی دستگاه کاربر). چکر scripts/check_win_wheels_closure.py
# بستار کامل وابستگی‌ها را از METADATA ویل‌ها راستی‌آزمایی می‌کند تا دیگر چیزی جا نیفتد.
PINS = [
    "fastapi==0.128.0",
    "annotated-doc==0.0.4",
    "uvicorn==0.44.0",
    "SQLAlchemy==2.0.58",
    "alembic==1.20.1",
    "pydantic==2.12.5",
    "pydantic-core==2.41.5",
    "pydantic-settings==2.13.1",
    "PyJWT==2.12.1",
    "cryptography==44.0.3",
    "pika==1.5.0",
    "httpx==0.28.1",
    "psycopg==3.3.9",
    "psycopg-binary==3.3.9",
    "tzdata==2026.1",
    "starlette==0.50.0",
    "anyio==4.13.0",
    "sniffio==1.3.1",
    "typing-extensions==4.15.0",
    "typing-inspection==0.4.2",
    "annotated-types==0.7.0",
    "click==8.1.8",
    "h11==0.16.0",
    "httptools==0.9.0",
    "watchfiles==1.3.0",
    "websockets==16.0",
    "python-dotenv==1.2.2",
    "PyYAML==6.0.3",
    "colorama==0.4.6",
    "httpcore==1.0.9",
    "certifi==2026.2.25",
    "idna==3.11",
    "Mako==1.4.3",
    "MarkupSafe==3.0.3",
    "greenlet==3.4.0",
    "cffi==2.0.0",
    "pycparser==3.0",
    "python-multipart==0.0.24",
    "orjson==3.11.8",
]


def canonical(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def main() -> int:
    if WHEELS.exists():
        for f in WHEELS.iterdir():
            f.unlink()
    else:
        WHEELS.mkdir(parents=True)
    failed: list[str] = []
    for pin in PINS:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "download", "-q", "--platform", "win_amd64",
             "--only-binary=:all:", "--no-deps", "-d", str(WHEELS), pin],
            capture_output=True, text=True)
        if r.returncode != 0:
            failed.append(pin)
            print(f"FAIL {pin}\n  {r.stderr.strip()[-200:]}")
    # کنترل یکتایی: هیچ دو ویلی با نام یکتای یکسان نباشد
    seen: dict[str, str] = {}
    dupes: list[str] = []
    for whl in sorted(WHEELS.glob("*.whl")):
        base = whl.name.split("-")[0]
        c = canonical(base)
        if c in seen:
            dupes.append(f"{seen[c]} + {whl.name}")
        seen[c] = whl.name
    print(f"wheels: {len(list(WHEELS.glob('*.whl')))} | canonical packages: {len(seen)}")
    if dupes:
        print("DUPLICATES:", dupes)
        return 1
    if failed:
        print("FAILED:", failed)
        return 1
    print("OK — all wheels downloaded, no duplicates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
