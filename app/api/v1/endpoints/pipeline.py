import logging
from typing import Any, Dict
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from app.core.pipeline import run_ai_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["AI Pipeline"])

# Simple in-memory tracker for pipeline run status
_pipeline_status = {
    "status": "idle",
    "last_run": None,
    "last_result": None,
    "error": None,
}


@router.post("/run", response_model=Dict[str, Any], status_code=status.HTTP_200_OK)
async def trigger_pipeline(
    batch_size: int = 50,
    min_cluster_size: int = 4,
    min_samples: int = 2,
):
    """
    Executes Phase 3 AI Processing Pipeline:
    1. Embeds un-embedded feedback in Supabase pgvector using all-MiniLM-L6-v2.
    2. Runs HDBSCAN unsupervised density clustering.
    3. Synthesizes structured themes via LLM (Gemini Flash / Groq) with 100% quote attribution.
    4. Calculates Revenue-at-Risk scores and persists themes.
    """
    global _pipeline_status
    _pipeline_status["status"] = "running"
    try:
        result = await run_ai_pipeline(
            batch_size=batch_size,
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
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
