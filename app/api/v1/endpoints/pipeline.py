import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from app.core.pipeline import run_ai_pipeline

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["AI Pipeline"])


class PipelineRunRequest(BaseModel):
    batch_size: Optional[int] = Field(default=50, ge=1, le=500)
    min_cluster_size: Optional[int] = Field(default=4, ge=2)
    min_samples: Optional[int] = Field(default=2, ge=1)


# Simple in-memory tracker for pipeline run status
_pipeline_status = {
    "status": "idle",
    "last_run": None,
    "last_result": None,
    "error": None,
}


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
    global _pipeline_status
    _pipeline_status["status"] = "running"
    try:
        result = await run_ai_pipeline(
            batch_size=eff_batch_size,
            min_cluster_size=eff_min_cluster_size,
            min_samples=eff_min_samples,
        )
        _pipeline_status["status"] = "idle"
        _pipeline_status["last_result"] = result
        return result
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}", exc_info=True)
        _pipeline_status["status"] = "failed"
        _pipeline_status["error"] = str(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution failed: {e}",
        )


@router.get("/status", response_model=Dict[str, Any])
async def get_pipeline_status():
    """Returns the current processing status of the AI pipeline."""
    return _pipeline_status
