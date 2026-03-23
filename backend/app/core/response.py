from typing import Any

from fastapi.responses import JSONResponse


def success_response(data: Any = None, msg: str = "ok", code: int = 200) -> dict[str, Any]:
    return {"code": code, "data": data, "msg": msg}


def error_response(status_code: int, msg: str, code: int | None = None) -> JSONResponse:
    err_code = code or status_code
    return JSONResponse(
        status_code=status_code,
        content={"code": err_code, "data": None, "msg": msg},
    )

