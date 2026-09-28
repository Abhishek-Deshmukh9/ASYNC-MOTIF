import json
import uuid
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_db
from app.models.feedback import FeedbackItem
from app.core.normalization import normalize_and_deduplicate
from app.schemas.feedback import FeedbackItemCreate, FeedbackItemResponse

router = APIRouter(prefix="/feedback", tags=["Feedback"])


@router.post("/upload", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def upload_feedback_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload raw JSON or CSV feedback file.
    Cleans, deduplicates, enforces metadata placeholders, and persists to PostgreSQL.
    """
    if not file.filename.endswith((".json", ".csv")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Please upload a .json or .csv file.",
        )

    content_bytes = await file.read()
    raw_items: List[Dict[str, Any]] = []

    if file.filename.endswith(".json"):
        try:
            parsed = json.loads(content_bytes.decode("utf-8"))
            if isinstance(parsed, list):
                raw_items = parsed
            else:
                raw_items = [parsed]
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse JSON file: {e}",
            )
    elif file.filename.endswith(".csv"):
        import csv
        import io
        try:
            reader = csv.DictReader(io.StringIO(content_bytes.decode("utf-8")))
            raw_items = [row for row in reader]
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to parse CSV file: {e}",
            )

    # Execute normalization & deduplication engine
    canonical_items, dupes_found = normalize_and_deduplicate(raw_items)

    # Persist to database
    db_items: List[FeedbackItem] = []
    for item in canonical_items:
        db_item = FeedbackItem(
            id=uuid.uuid4(),
            source_type=item.source_type,
            external_id=item.external_id,
            content=item.content,
            clean_content=item.clean_content,
            customer_id=item.customer_id,
            customer_tier=item.customer_tier,
            arr_value=item.arr_value,
            churn_risk_flag=item.churn_risk_flag,
            metadata_=item.metadata,
        )
        db_items.append(db_item)

    db.add_all(db_items)
    await db.commit()

    return {
        "message": f"Successfully ingested {len(canonical_items)} canonical feedback records.",
        "filename": file.filename,
        "raw_items_count": len(raw_items),
        "canonical_persisted_count": len(canonical_items),
        "duplicates_merged": dupes_found,
    }


@router.get("", response_model=List[FeedbackItemResponse])
async def list_feedback_items(
    limit: int = 100,
    offset: int = 0,
    source_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List ingested feedback items with pagination and optional source_type filter."""
    query = select(FeedbackItem).offset(offset).limit(limit)
    if source_type:
        query = query.where(FeedbackItem.source_type == source_type)

    result = await db.execute(query)
    return result.scalars().all()
