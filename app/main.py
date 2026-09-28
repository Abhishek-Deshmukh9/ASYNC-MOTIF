import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.v1.router import api_router
from app.db.session import check_db_health, init_db

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("motif")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context for startup and shutdown events."""
    logger.info(f"Starting {settings.PROJECT_NAME} backend in {settings.ENVIRONMENT} mode...")
    
    # Check database and pgvector connection on startup
    db_health = await check_db_health()
    if db_health.get("database") == "connected":
        logger.info(
            f"Database connected successfully. pgvector extension: {db_health.get('pgvector_extension')} "
            f"(latency: {db_health.get('latency_ms')}ms)"
        )
        try:
            await init_db()
        except Exception as e:
            logger.warning(f"Could not auto-run init_db on startup: {e}")
    else:
        logger.warning(
            f"Database not yet reachable on startup ({db_health.get('error')}). "
            "It will be connected when PostgreSQL container is ready."
        )

    yield

    logger.info(f"Shutting down {settings.PROJECT_NAME} backend...")


# Initialize FastAPI application
app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "Autonomous feedback-to-backlog pipeline with HDBSCAN density clustering, "
        "Revenue-at-Risk prioritization, and human-in-the-loop PM approval gate."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API v1 routes
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["Root"])
async def root():
    return {
        "service": settings.PROJECT_NAME,
        "tagline": "Your users already wrote the roadmap.",
        "status": "operational",
        "docs_url": "/docs",
        "health_url": f"{settings.API_V1_PREFIX}/health",
    }
