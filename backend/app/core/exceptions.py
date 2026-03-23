import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError

from .response import error_response

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return error_response(exc.status_code, detail)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError):
        first_error = exc.errors()[0] if exc.errors() else {"msg": "参数校验失败"}
        loc = ".".join(str(part) for part in first_error.get("loc", []))
        msg = first_error.get("msg", "参数校验失败")
        detail = f"{loc}: {msg}" if loc else msg
        return error_response(422, detail)

    @app.exception_handler(Exception)
    async def internal_exception_handler(_: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return error_response(500, "服务器内部错误")

