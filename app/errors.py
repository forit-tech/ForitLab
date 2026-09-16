"""Единый формат ошибок: всегда {"error": {"code", "message", "detail"}}."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """Ошибка домена: сама знает свой HTTP-код и машинный код."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, detail: object | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "payload_too_large"


class UnprocessableDataError(AppError):
    """Файл прочитан, но данные не годятся для анализа."""

    status_code = 422
    code = "unprocessable_data"


class StorageUnavailableError(AppError):
    """Хостинг не дал записать состояние — фиксируем, а не обходим хаками."""

    status_code = 503
    code = "storage_unavailable"


_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    503: "service_unavailable",
}


def error_payload(code: str, message: str, detail: object | None = None) -> dict:
    body: dict[str, object] = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return {"error": body}


def _error(status_code: int, code: str, message: str, detail: object | None = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_payload(code, message, detail))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ")
        detail = None if isinstance(exc.detail, str) else exc.detail
        return _error(exc.status_code, code, message, detail)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, "validation_error", "Запрос не прошёл валидацию", exc.errors())

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # На shared hosting трейс уезжает в stderr.log Passenger'а.
        return _error(500, "internal_error", "Внутренняя ошибка сервиса", type(exc).__name__)
