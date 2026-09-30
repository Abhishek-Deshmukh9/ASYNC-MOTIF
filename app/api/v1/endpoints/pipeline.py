import asyncio
import logging
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.core.auth import CurrentUser, get_current_user
from app.core.projects import authorize_project
from app.core.pipeline import run_ai_pipeline

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["AI Pipeline"])


class PipelineRunRequest(BaseModel):
    batch_size: Optional[int] = Field(default=50, ge=1, le=500)
    min_cluster_size: Optional[int] = Field(default=4, ge=2)
    min_samples: Optional[int] = Field(default=2, ge=1)
    project_id: Optional[str] = Field(default=None, max_length=255)


# In-memory run tracker, one entry per scope (a project id, or the demo corpus).
DEMO_SCOPE = "__demo__"
_runs: Dict[str, Dict[str, Any]] = {}
_tasks: Dict[str, "asyncio.Task[Any]"] = {}


def _blank_run() -> Dict[str, Any]:
    return {"status": "idle", "stage": None, "done": 0, "total": 0, "started_at": None, "last_run": None, "last_result": None, "error": None}


def _run_for(scope: str) -> Dict[str, Any]:
    return _runs.setdefault(scope, _blank_run())


async def _execute(scope: str, **kwargs: Any) -> Dict[str, Any]:
    """Run the pipeline for one scope, recording progress and the outcome."""
    run = _run_for(scope)
    run.update(status="running", stage="embedding", done=0, total=0, started_at=time.time(), error=None)

    def progress(stage: str, done: int = 0, total: int = 0) -> None:
        run.update(stage=stage, done=done, total=total)

    try:
        result = await run_ai_pipeline(progress=progress, **kwargs)
        run.update(status="idle", stage=None, last_result=result, last_run=time.time())
        return result
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        run.update(status="failed", stage=None, error=str(e))
        raise


@router.post("/run", response_model=Dict[str, Any], status_code=status.HTTP_200_OK)
async def trigger_pipeline(
    payload: Optional[PipelineRunRequest] = None,
    batch_size: Optional[int] = None,
    min_cluster_size: Optional[int] = None,
    min_samples: Optional[int] = None,
    background: bool = False,
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """
    Executes the AI processing pipeline:
    1. Embeds un-embedded feedback in Supabase pgvector using all-MiniLM-L6-v2.
    2. Runs HDBSCAN unsupervised density clustering.
    3. Synthesizes structured themes via LLM (Groq / Gemini) with 100% quote attribution.
    4. Calculates Revenue-at-Risk scores and persists themes.

    With ?background=true it returns at once ({"status": "running"}) and the run continues on the
    server; poll GET /pipeline/status for stage-by-stage progress and the final result.
    Without it the request waits for the finished result.
    """
    eff_batch_size = (
        payload.batch_size if payload and payload.batch_size is not None
        else (batch_size if batch_size is not None else 50)
    )
    eff_min_cluster_size = (
        payload.min_cluster_size if payload and payload.min_cluster_size is not None
        else (min_cluster_size if min_cluster_size is not None else 4)
    )
    eff_min_samples = (
        payload.min_samples if payload and payload.min_samples is not None
        else (min_samples if min_samples is not None else 2)
    )
    project_id = payload.project_id if payload else None
    await authorize_project(db, project_id, user)
    scope = project_id or DEMO_SCOPE
    kwargs = dict(batch_size=eff_batch_size, min_cluster_size=eff_min_cluster_size, min_samples=eff_min_samples, project_id=project_id)

    run = _run_for(scope)
    if run["status"] == "running":
        if background:
            return {"status": "running", "already_running": True, **_public(run)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An analysis is already running for this project. Wait for it to finish.")

    if background:
        run.update(status="running", stage="embedding", done=0, total=0, started_at=time.time(), error=None)

        async def _job() -> None:
            try:
                await _execute(scope, **kwargs)
            except Exception:
                pass  # recorded on the run; the page reads it from /pipeline/status
            finally:
                _tasks.pop(scope, None)

        _tasks[scope] = asyncio.create_task(_job())
        return {"status": "running", **_public(run)}

    try:
        return await _execute(scope, **kwargs)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution failed: {e}",
        )


def _public(run: Dict[str, Any]) -> Dict[str, Any]:
    elapsed = round(time.time() - run["started_at"], 1) if run["status"] == "running" and run["started_at"] else None
    return {**run, "elapsed_seconds": elapsed}


@router.get("/status", response_model=Dict[str, Any])
async def get_pipeline_status(
    project_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """Progress of the pipeline for one project (or the demo corpus when project_id is omitted)."""
    await authorize_project(db, project_id, user)
    return _public(_run_for(project_id or DEMO_SCOPE))
