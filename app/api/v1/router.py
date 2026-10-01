from fastapi import APIRouter, Depends
from app.api.v1.endpoints import health, connections, feedback, inbox, members, pipeline, projects, sources, themes, metrics
from app.core.auth import get_current_user

api_router = APIRouter()

# Health stays public (uptime checks). Everything else needs a signed-in user when auth is on.
api_router.include_router(health.router, tags=["Health"])

protected = [Depends(get_current_user)]
api_router.include_router(projects.router, dependencies=protected)
api_router.include_router(members.router, dependencies=protected)
api_router.include_router(feedback.router, dependencies=protected)
api_router.include_router(sources.router, dependencies=protected)
api_router.include_router(connections.router, dependencies=protected)
api_router.include_router(pipeline.router, dependencies=protected)
api_router.include_router(themes.router, dependencies=protected)
api_router.include_router(metrics.router, dependencies=protected)
api_router.include_router(inbox.router, dependencies=protected)
# The webhook link is its own credential (only its hash is stored), so it sits outside sign-in
api_router.include_router(inbox.hook_router)
