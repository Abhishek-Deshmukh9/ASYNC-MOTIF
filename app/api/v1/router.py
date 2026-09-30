from fastapi import APIRouter
from app.api.v1.endpoints import health, feedback, pipeline, sources, themes, metrics

api_router = APIRouter()

# Include health router
api_router.include_router(health.router, tags=["Health"])

# Include feedback router
api_router.include_router(feedback.router)

# Include project sources router (file uploads, Obsidian vaults)
api_router.include_router(sources.router)

# Include AI pipeline router
api_router.include_router(pipeline.router)

# Include themes router
api_router.include_router(themes.router)

# Include metrics router
api_router.include_router(metrics.router)
