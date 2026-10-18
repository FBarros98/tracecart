from fastapi import APIRouter, Response, status

from app.database.session import check_database
from app.schemas.common import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A required dependency is unavailable"}},
)
async def readiness(response: Response) -> HealthResponse:
    if await check_database():
        return HealthResponse(status="ok", checks={"database": "ok"})
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable", checks={"database": "unavailable"})
