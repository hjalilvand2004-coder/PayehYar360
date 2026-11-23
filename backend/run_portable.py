"""اجرای پرتیبل هسته مشترک — بدون نیاز به نصب Python/PyCharm.

باینری PyInstaller: همه وابستگی‌ها و فرانت build‌شده داخل فایل اجرایی است.
داده (SQLite + Snapshotها) در پوشه data/ کنار باینری ساخته می‌شود.

حالت پیش‌فرض پرتیبل: dev/demo (SQLite + داده نمونه + ورود آزمایشی).
برای اتصال به PostgreSQL/SSO واقعی، متغیرهای محیطی را مطابق docs/07-deployment.md تنظیم کنید.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _base() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller onefile/onedir
        return Path(sys._MEIPASS)  # noqa: SLF001
    return Path(__file__).resolve().parent


def main() -> None:
    base = _base()
    cwd = Path.cwd()

    os.environ.setdefault("ENV", "dev")
    os.environ.setdefault("PORT", "8094")
    data_dir = cwd / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{(data_dir / 'core.db').as_posix()}")
    os.environ.setdefault("DATA_DIR", str(data_dir))
    os.environ.setdefault("AUTO_CREATE_TABLES", "true")
    os.environ.setdefault("SEED_DEMO", "true")
    os.environ.setdefault("WORKERS_IN_PROCESS", "true")
    os.environ.setdefault("DEV_AUTH", "true")
    os.environ.setdefault("ALLOWED_ORIGINS", "http://188.212.96.235:8094,http://localhost:8094,http://127.0.0.1:8094")

    dist = base / "frontend_dist"
    if dist.is_dir():
        os.environ.setdefault("SERVE_FRONTEND_DIR", str(dist))

    import uvicorn  # پس از تنظیم env

    from app.main import app

    port = int(os.environ["PORT"])
    print("=" * 56)
    print("  PayehYar360 — Shared Core & Master Data (portable v1.0.9)")
    print(f"  Panel & API:  http://localhost:{port}")
    print(f"  Swagger:      http://localhost:{port}/docs")
    print(f"  Data dir:     {data_dir}")
    print("  Stop:         Ctrl+C")
    print("=" * 56)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
