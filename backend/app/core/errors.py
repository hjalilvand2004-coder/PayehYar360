"""قرارداد یکسان خطا (بخش ۸.۳ سند فنی)."""
from __future__ import annotations

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, code: str, message: str, status_code: int | None = None, details: dict | None = None):
        self.code = code
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def unauthorized(msg: str = "هویت درخواست معتبر نیست.") -> AppError:
    return AppError("UNAUTHENTICATED", msg, 401)


def forbidden(code: str, msg: str, details: dict | None = None) -> AppError:
    return AppError(code, msg, 403, details)


def not_found(msg: str = "داده موردنظر یافت نشد یا در محدوده مجاز شما قابل مشاهده نیست.") -> AppError:
    return AppError("NOT_FOUND", msg, 404)


def conflict(code: str, msg: str, details: dict | None = None) -> AppError:
    return AppError(code, msg, 409, details)


def version_conflict(current_version: int) -> AppError:
    return AppError("VERSION_CONFLICT", "این رکورد در فاصله دریافت و ارسال شما تغییر کرده است؛ نسخه جدید را بارگیری کنید.",
                    412, {"current_version": current_version})


def cursor_expired() -> AppError:
    return AppError("CURSOR_EXPIRED", "نشانگر همگام‌سازی منقضی شده است؛ Snapshot جدید دریافت کنید.", 410)


def rate_limited() -> AppError:
    return AppError("RATE_LIMITED", "تعداد درخواست‌ها بیش از حد مجاز است؛ بعداً تلاش کنید.", 429)


def _payload(request: Request, code: str, message: str, details: dict | None) -> dict:
    return {
        "code": code,
        "message": message,
        "correlation_id": getattr(request.state, "correlation_id", None),
        **({"details": details} if details else {}),
    }


def register_error_handlers(app):
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_payload(request, exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        details = {"errors": [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]}
        return JSONResponse(status_code=422, content=_payload(request, "INVALID_INPUT", "ورودی ارسالی معتبر نیست.", details))

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):  # pragma: no cover
        import logging
        logging.getLogger("core").exception("Unhandled error", exc_info=exc)
        msg = "خطای غیرمنتظره در سرور رخ داد."
        if settings_env := getattr(request.app.state, "env", "dev"):
            if settings_env != "prod":
                msg = f"خطای غیرمنتظره: {type(exc).__name__}: {exc}"
        return JSONResponse(status_code=500, content=_payload(request, "INTERNAL_ERROR", msg, None))
