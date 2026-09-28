from fastapi import APIRouter
from app.config import settings
from app.db.session import check_db_health
from app.schemas.health import HealthCheckResponse, DatabaseHealth

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Health check and pgvector verification",
    description="Returns backend service status and verifies PostgreSQL connection with pgvector extension.",
)
async def get_health() -> HealthCheckResponse:
    db_health_data = await check_db_health()

    is_healthy = (
        db_health_data.get("database") == "connected"
        and db_health_data.get("pgvector_extension") == "enabled"
    )

    return HealthCheckResponse(
        status="healthy" if is_healthy else "degraded",
        service=settings.PROJECT_NAME,
        version="0.1.0",
        environment=settings.ENVIRONMENT,
        database=DatabaseHealth(
            database=db_health_data.get("database", "disconnected"),
            pgvector_extension=db_health_data.get("pgvector_extension", "disabled"),
            latency_ms=db_health_data.get("latency_ms"),
            error=db_health_data.get("error"),
        ),
    )
