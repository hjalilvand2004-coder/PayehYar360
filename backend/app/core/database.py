"""راه‌اندازی موتور دیتابیس و نشست‌ها — SQLAlchemy 2.0 (همگام)."""
from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_connect_args: dict = {}
_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "pool_size": settings.DB_POOL_SIZE,
    "max_overflow": settings.DB_MAX_OVERFLOW,
}

if settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs = {"pool_pre_ping": False, "connect_args": {"timeout": 30, "check_same_thread": False}}

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)

if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_conn, _rec):  # pragma: no cover
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def get_db():
    """نشست درخواست؛ تراکنش توسط لایه سرویس/مسیر با commit صریح مدیریت می‌شود."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
