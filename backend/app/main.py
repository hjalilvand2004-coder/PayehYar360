"""نقطه ورود هسته مشترک — FastAPI با معماری ماژولار (بخش ۵ و ۶ سند فنی)."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid as uuid_mod
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.errors import rate_limited, register_error_handlers

logging.basicConfig(
    level=logging.DEBUG if settings.ENV == "dev" else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("core")

API = settings.API_PREFIX

# ---------------- متریک‌ها (Prometheus text) ----------------
_metrics_lock = threading.Lock()
_req_counts: dict = defaultdict(int)
_req_durations_sum: dict = defaultdict(float)


def _norm_path(path: str) -> str:
    path = re.sub(r"/[0-9a-fA-F-]{36}", "/:id", path)
    path = re.sub(r"/\d+", "/:num", path)
    return path


# ---------------- محدودسازی نرخ ----------------
_rate_lock = threading.Lock()
_rate_buckets: dict = defaultdict(deque)
UNLIMITED_PATHS = ("/health", "/metrics", "/docs", "/redoc", "/openapi.json")


def _client_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return "tok:" + auth[7:].strip()[:24]
    dev = request.headers.get("x-dev-user")
    if dev:
        return "dev:" + dev
    return "ip:" + (request.client.host if request.client else "?")


async def _metrics_rate_middleware(request: Request, call_next):
    start = time.time()
    if settings.RATE_LIMIT_PER_MINUTE > 0 and request.url.path.startswith("/api") and \
            not any(request.url.path.startswith(p) for p in UNLIMITED_PATHS):
        key = _client_key(request)
        now = time.time()
        with _rate_lock:
            bucket = _rate_buckets[key]
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= settings.RATE_LIMIT_PER_MINUTE:
                err = rate_limited()
                return JSONResponse(status_code=429, content={
                    "code": err.code, "message": err.message,
                    "correlation_id": getattr(request.state, "correlation_id", None)})
            bucket.append(now)
    response = await call_next(request)
    duration = time.time() - start
    norm = _norm_path(request.url.path)
    with _metrics_lock:
        _req_counts[f"{norm}|{request.method}|{response.status_code}"] += 1
        _req_durations_sum[f"{norm}|{request.method}"] += duration
    response.headers["X-Correlation-Id"] = getattr(request.state, "correlation_id", "")
    return response


async def _correlation_middleware(request: Request, call_next):
    cid = request.headers.get("x-correlation-id") or str(uuid_mod.uuid4())
    request.state.correlation_id = cid
    request.state.started_at = time.time()
    return await call_next(request)


# ---------------- چرخه عمر ----------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.database import engine
    from app.db_models import Base  # ثبت همه مدل‌ها

    if settings.AUTO_CREATE_TABLES:
        Base.metadata.create_all(engine)
        log.info("Tables ensured (AUTO_CREATE_TABLES=true) — در تولید از Alembic استفاده کنید.")
    if settings.SEED_DEMO:
        from app.seed import seed_demo
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            seed_demo(db)
        finally:
            db.close()

    app.state.workers = []
    if settings.WORKERS_IN_PROCESS:
        from app.workers import job_worker, outbox_worker
        app.state.workers.append(outbox_worker.start())
        app.state.workers.append(job_worker.start())
        log.info("In-process workers started (demo mode)")
    yield
    if settings.WORKERS_IN_PROCESS:
        from app.workers import job_worker, outbox_worker
        outbox_worker.stop()
        job_worker.stop()
    log.info("Shutdown complete")


app = FastAPI(
    title="PayehYar360 — Shared Core & Master Data",
    description="هسته مشترک و اطلاعات پایه پلتفرم دانشجو۳۶۰ (پایه‌یار۳۶۰) — شرکت ماه‌افزار هوشمند رسا",
    version="1.0.5",
    lifespan=lifespan,
    docs_url="/docs", redoc_url="/redoc", openapi_url="/openapi.json",
)

app.state.env = settings.ENV

# ترتیب middleware: metrics/rate اول ثبت می‌شود تا correlation بیرونی‌تر و پیش‌تر اجرا شود
app.middleware("http")(_metrics_rate_middleware)
app.middleware("http")(_correlation_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-Id", "Idempotent-Replay"],
)

register_error_handlers(app)

# ---------------- روترهای API ----------------
from app.modules.audit.router import router as audit_router  # noqa: E402
from app.modules.change_requests.router import router as change_requests_router  # noqa: E402
from app.modules.data_quality.router import router as quality_router  # noqa: E402
from app.modules.identities.router import router as identities_router  # noqa: E402
from app.modules.integrations.router import router as integrations_router  # noqa: E402
from app.modules.organizations.router import router as organizations_router  # noqa: E402
from app.modules.ownership.router import router as ownership_router  # noqa: E402
from app.modules.persons.router import router as persons_router  # noqa: E402
from app.modules.references.router import router as references_router  # noqa: E402
from app.modules.synchronization.router import router as sync_router  # noqa: E402

app.include_router(persons_router, prefix=API)
app.include_router(identities_router, prefix=API)
app.include_router(organizations_router, prefix=API)
app.include_router(references_router, prefix=API)
app.include_router(ownership_router, prefix=API)
app.include_router(change_requests_router, prefix=API)
app.include_router(quality_router, prefix=API)
app.include_router(sync_router, prefix=API)
app.include_router(integrations_router, prefix=API)
app.include_router(audit_router, prefix=API)

from app.auth_router import router as auth_router  # noqa: E402

app.include_router(auth_router, prefix=API)


# ---------------- meta / health / metrics ----------------
@app.get(f"{API}/meta", tags=["meta"])
def meta():
    from app.core.config import settings as s
    from app.messaging import rabbitmq
    out = {
        "app": "payehyar360-shared-core",
        "version": "1.0.5",
        "env": s.ENV,
        "auth_mode": "dev" if s.DEV_AUTH else "oidc",
        "dev_mode": s.DEV_AUTH,
        "oidc": {
            "issuer": s.OIDC_ISSUER,
            "client_id": s.OIDC_CLIENT_ID or None,
            "authorization_endpoint": None,
            "end_session_endpoint": None,
            "available": False,
        },
        "sso": {
            "access_role": s.SSO_ACCESS_ROLE,
            "default_tenant": s.SSO_DEFAULT_TENANT,
            "login_path": "/api/v1/auth/sso/login",
            "callback_path": "/api/v1/auth/sso/callback",
        },
        "rabbitmq": rabbitmq.state(),
    }
    if not s.DEV_AUTH:
        try:
            doc = oidc_metadata()
            out["oidc"]["authorization_endpoint"] = doc.get("authorization_endpoint")
            out["oidc"]["end_session_endpoint"] = doc.get("end_session_endpoint")
            out["oidc"]["available"] = True
        except Exception as exc:  # noqa: BLE001
            out["oidc"]["error"] = str(exc)
    return out


@app.get("/health/live", tags=["health"])
def health_live():
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def health_ready():
    from app.core.database import engine
    from sqlalchemy import text
    from app.messaging import rabbitmq
    db_ok = True
    detail = "ok"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        detail = f"{type(exc).__name__}: {exc}"
    return {
        "status": "ok" if db_ok else "degraded",
        "checks": {
            "database": {"ok": db_ok, "detail": detail},
            # قطع RabbitMQ لزوماً API را از دسترس خارج نمی‌کند؛ Outbox موقتاً نگه می‌دارد
            "rabbitmq": {"ok": rabbitmq.state()["connected"] or not settings.RABBITMQ_URL,
                         "detail": rabbitmq.state()["detail"]},
        },
    }


@app.get("/metrics", tags=["health"])
def metrics():
    lines = []
    with _metrics_lock:
        for key, count in sorted(_req_counts.items()):
            path, method, code = key.split("|")
            lines.append(f'api_requests_total{{path="{path}",method="{method}",code="{code}"}} {count}')
        for key, total in sorted(_req_durations_sum.items()):
            path, method = key.split("|")
            lines.append(f'api_request_seconds_sum{{path="{path}",method="{method}"}} {total:.4f}')
    try:
        from app.core.database import SessionLocal
        from app.modules.integrations.service import outbox_stats
        db = SessionLocal()
        try:
            st = outbox_stats(db)
        finally:
            db.close()
        lines.append(f"outbox_pending {st['pending']}")
        lines.append(f"outbox_failed {st['failed']}")
        if st["oldest_pending_age_seconds"] is not None:
            lines.append(f"outbox_oldest_pending_age_seconds {st['oldest_pending_age_seconds']}")
    except Exception:  # noqa: BLE001
        pass
    from app.messaging import rabbitmq
    lines.append(f"rabbitmq_connected {1 if rabbitmq.state()['connected'] else 0}")
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


# ---------------- سرو فرانت یکپارچه (SPA) ----------------
FRONTEND_DIR = settings.SERVE_FRONTEND_DIR or ""
if FRONTEND_DIR and os.path.isdir(FRONTEND_DIR):
    assets_dir = os.path.join(FRONTEND_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith(("api/", "health", "metrics", "docs", "redoc", "openapi.json", "assets/")):
            return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": "یافت نشد."})
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    log.info("Serving frontend from %s", FRONTEND_DIR)
