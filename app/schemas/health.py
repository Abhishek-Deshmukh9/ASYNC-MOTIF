from typing import Optional
from pydantic import BaseModel, Field


class DatabaseHealth(BaseModel):
    database: str = Field(..., description="PostgreSQL connection status ('connected' or 'disconnected')")
    pgvector_extension: str = Field(..., description="pgvector extension status ('enabled' or 'disabled')")
    latency_ms: Optional[float] = Field(None, description="Database ping latency in milliseconds")
    error: Optional[str] = Field(None, description="Error message if health check failed")


class HealthCheckResponse(BaseModel):
    status: str = Field(..., description="Overall service status ('healthy' or 'degraded')")
    service: str = Field(..., description="Service identifier")
    version: str = Field(..., description="Application version")
    environment: str = Field(..., description="Operating environment")
    database: DatabaseHealth
