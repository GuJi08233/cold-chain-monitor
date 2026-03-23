from fastapi import APIRouter

from ..core.response import success_response

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict:
    return success_response(
        data={"status": "ok", "service": "cold-chain-backend"},
        msg="ok",
    )

