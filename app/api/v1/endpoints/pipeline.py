import asyncio
import json
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import StreamingResponse
from app.core.pipeline import run_ai_pipeline, pipeline_progress

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["AI Pipeline"])


class PipelineRunRequest(BaseModel):
    batch_size: Optional[int] = Field(default=50, ge=1, le=500)
    min_cluster_size: Optional[int] = Field(default=4, ge=2)
    min_samples: Optional[int] = Field(default=2, ge=1)
    project_id: Optional[str] = Field(default=None, max_length=255)


async def _run_pipeline_bg(
    batch_size: int,
    min_cluster_size: int,
    min_samples: int,
    project_id: Optional[str],
) -> None:
    """Background wrapper so exceptions are caught and recorded."""
    try:
        await run_ai_pipeline(
            batch_size=batch_size,
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            project_id=project_id,
        )
    except Exception as e:
        logger.error(f"Background pipeline failed: {e}", exc_info=True)


@router.post("/run", response_model=Dict[str, Any], status_code=status.HTTP_200_OK)
async def trigger_pipeline(
    payload: Optional[PipelineRunRequest] = None,
    batch_size: Optional[int] = None,
    min_cluster_size: Optional[int] = None,
    min_samples: Optional[int] = None,
):
    """
    Executes Phase 3 AI Processing Pipeline:
    1. Embeds un-embedded feedback in Supabase pgvector using all-MiniLM-L6-v2.
    2. Runs HDBSCAN unsupervised density clustering.
    3. Synthesizes structured themes via LLM (Groq / Gemini) with 100% quote attribution.
    4. Calculates Revenue-at-Risk scores and persists themes.
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

    if pipeline_progress.status == "running":
        # Don't allow concurrent pipeline runs
        return {
            "status": "already_running",
            "message": "Pipeline is already running. Check /pipeline/status for progress.",
            **pipeline_progress.snapshot(),
        }

    # Run inline (keeps backward compat with frontend that awaits the response)
    try:
        result = await run_ai_pipeline(
            batch_size=eff_batch_size,
            min_cluster_size=eff_min_cluster_size,
            min_samples=eff_min_samples,
            project_id=payload.project_id if payload else None,
        )
        return result
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution failed: {e}",
        )


@router.get("/status", response_model=Dict[str, Any])
async def get_pipeline_status():
    """Returns the current processing status of the AI pipeline with stage-level detail."""
    return pipeline_progress.snapshot()


@router.get("/progress")
async def stream_pipeline_progress():
    """
    Server-Sent Events (SSE) endpoint for real-time pipeline progress.
    The frontend opens an EventSource connection here and receives
    stage updates as they happen.
    """
    queue = pipeline_progress.subscribe()

    async def event_stream():
        try:
            # Send the current snapshot immediately so the client has a baseline
            yield f"data: {json.dumps(pipeline_progress.snapshot())}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(msg)}\n\n"
                    # Stop when pipeline completes or fails
                    if msg.get("stage") in ("completed", "failed"):
                        break
                except asyncio.TimeoutError:
                    # Keepalive so proxies don't drop the connection
                    yield ": keepalive\n\n"
        finally:
            pipeline_progress.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
