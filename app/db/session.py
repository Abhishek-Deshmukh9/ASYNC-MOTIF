import logging
from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.db.base import Base

logger = logging.getLogger(__name__)

# Create async engine with connection pooling
engine = create_async_engine(
    settings.async_database_url,
    echo=(settings.ENVIRONMENT == "development"),
    future=True,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing database sessions to endpoints."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db_health() -> dict:
    """
    Validates PostgreSQL connectivity and checks whether the pgvector extension is functional.
    Returns status dictionary with connection status and pgvector support.
    """
    health_status = {
        "database": "disconnected",
        "pgvector_extension": "unknown",
        "latency_ms": None,
        "error": None,
    }

    try:
        import time
        start_time = time.time()
        async with engine.connect() as conn:
            # 1. Test basic connectivity
            await conn.execute(text("SELECT 1;"))
            latency_ms = round((time.time() - start_time) * 1000, 2)
            health_status["database"] = "connected"
            health_status["latency_ms"] = latency_ms

            # 2. Test pgvector extension explicitly
            result = await conn.execute(
                text("SELECT '[1,2,3]'::vector AS test_vector;")
            )
            row = result.fetchone()
            if row and row[0] is not None:
                health_status["pgvector_extension"] = "enabled"
            else:
                health_status["pgvector_extension"] = "disabled"

    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        health_status["database"] = "error"
        health_status["error"] = str(e)

    return health_status


async def init_db() -> None:
    """Initialize database extensions and schema tables."""
    try:
        async with engine.begin() as conn:
            # Enable vector extension
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "vector";'))
            # Create tables
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database schema initialized with vector extension.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
