"""
Turning an extracted document into stored passages, shared by file uploads and connectors.

`store_document` is used by connectors: a document from Notion, Drive or Slack keeps the same
source row every sync. Unchanged text is skipped, edited text replaces the old passages.
"""
import hashlib
import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.chunking import chunk_text
from app.core.extraction import ExtractedDocument
from app.core.normalization import clean_text, detect_churn_intent, normalize_and_deduplicate
from app.models.feedback import FeedbackItem
from app.models.project import Source

def content_hash(document: ExtractedDocument) -> str:
    payload = document.text if not document.rows else json.dumps(document.rows, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_passages(document: ExtractedDocument, project_id: str, source_id: uuid.UUID, kind: str) -> List[FeedbackItem]:
    """Build the feedback_items rows for one extracted document."""
    base_meta = {"project_id": project_id, "source_name": document.title, "source_path": document.path}
    items: List[FeedbackItem] = []

    if document.rows:
        # One piece of feedback per table row: customer, tier and ARR columns carry through
        normalized, _ = normalize_and_deduplicate(
            [dict(row, metadata=dict(base_meta, row=i + 1)) for i, row in enumerate(document.rows)]
        )
        for i, item in enumerate(normalized):
            items.append(
                FeedbackItem(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    source_id=source_id,
                    chunk_index=i,
                    source_type=item.source_type[:50],
                    external_id=f"{source_id}:{i}",
                    content=item.content,
                    clean_content=item.clean_content,
                    customer_id=item.customer_id,
                    customer_tier=item.customer_tier,
                    arr_value=item.arr_value,
                    churn_risk_flag=item.churn_risk_flag,
                    metadata_=item.metadata,
                )
            )
        return items

    source_type = "meeting_transcript" if kind == "meeting" else ("note" if document.kind == "note" else "document")
    for chunk in chunk_text(document.text):
        cleaned = clean_text(chunk.text)
        if len(cleaned) < 3:
            continue
        items.append(
            FeedbackItem(
                id=uuid.uuid4(),
                project_id=project_id,
                source_id=source_id,
                chunk_index=chunk.index,
                speaker=(chunk.speaker or None) and chunk.speaker[:255],
                source_type=source_type,
                external_id=f"{source_id}:{chunk.index}",
                content=chunk.text,
                clean_content=cleaned,
                customer_id=None,
                customer_tier="free",
                arr_value=0,
                churn_risk_flag=detect_churn_intent(cleaned),
                metadata_=dict(base_meta, section=chunk.section) if chunk.section else base_meta,
            )
        )
    return items




async def store_document(
    db: AsyncSession,
    pid: uuid.UUID,
    project_id: str,
    document: ExtractedDocument,
    kind: str,
    *,
    connection_id: uuid.UUID,
    external_id: str,
    url: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add or refresh one connector document. Returns {"status": imported | updated | unchanged | skipped,
    "source_id": ..., "passages": n}. The caller commits.
    """
    digest = content_hash(document)
    existing = await db.scalar(select(Source).where(Source.connection_id == connection_id, Source.external_id == external_id))
    if existing is not None and existing.content_hash == digest:
        return {"status": "unchanged", "source_id": str(existing.id), "passages": 0}

    source_id = existing.id if existing is not None else uuid.uuid4()
    passages: List[FeedbackItem] = await run_in_threadpool(build_passages, document, project_id, source_id, kind)
    if provider:
        for item in passages:
            item.metadata_ = dict(item.metadata_ or {}, provider=provider)

    if existing is not None:
        await db.execute(delete(FeedbackItem).where(FeedbackItem.source_id == source_id))
        if not passages:
            await db.execute(delete(Source).where(Source.id == source_id))
            return {"status": "skipped", "source_id": None, "passages": 0}
        existing.title = document.title[:500]
        existing.content_hash = digest
        existing.url = url
        db.add_all(passages)
        await db.flush()
        return {"status": "updated", "source_id": str(source_id), "passages": len(passages)}

    if not passages:
        return {"status": "skipped", "source_id": None, "passages": 0}
    db.add(Source(
        id=source_id, project_id=pid, connection_id=connection_id, external_id=external_id[:1000],
        title=document.title[:500], url=url, mime_type=document.mime_type, content_hash=digest,
    ))
    await db.flush()
    db.add_all(passages)
    await db.flush()
    return {"status": "imported", "source_id": str(source_id), "passages": len(passages)}
