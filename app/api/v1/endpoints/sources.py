"""
Project sources: upload files (documents, notes, exported tables, Obsidian vaults),
list them, and remove them.

An upload is extracted to text, split into passages, and stored as feedback_items
linked to a row in `sources`. The existing pipeline then embeds and clusters the
passages like any other feedback, scoped to the project.
"""
import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_db
from app.core.auth import CurrentUser, get_current_user
from app.core.projects import authorize_project, ensure_project, project_uuid, validate_project_id
from app.core.extraction import MAX_FILE_BYTES, ExtractedDocument, ExtractionError, extract_file
from app.core.ingest import build_passages as _passages, content_hash as _content_hash
from app.models.feedback import FeedbackItem
from app.models.project import Project, Source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["Sources"])

MAX_FILES_PER_REQUEST = 100
MAX_PASSAGES_PER_REQUEST = 10_000
SOURCE_KINDS = {"document", "note", "meeting", "table"}
def _source_payload(source: Source, passages: int) -> Dict[str, Any]:
    return {
        "id": str(source.id),
        "title": source.title,
        "path": source.external_id,
        "mime_type": source.mime_type,
        "connection_id": str(source.connection_id) if source.connection_id else None,
        "url": source.url,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "passages": passages,
    }


@router.post("/upload", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def upload_sources(
    project_id: str = Form(...),
    project_name: Optional[str] = Form(default=None),
    kind: str = Form(default="document"),
    files: List[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """
    Add files to a project. Accepts PDF, Word, PowerPoint, Excel, HTML, Markdown,
    text, CSV, JSON, and .zip archives (for example an Obsidian vault).
    Each file is reported as imported, duplicate, skipped or failed; one bad file
    does not stop the others.
    """
    project_id = validate_project_id(project_id)
    kind = kind if kind in SOURCE_KINDS else "document"
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Upload at most {MAX_FILES_PER_REQUEST} files at a time.")

    await authorize_project(db, project_id, user)
    pid = await ensure_project(db, project_id, project_name, user)
    await db.commit()

    results: List[Dict[str, Any]] = []
    total_passages = 0
    for upload in files:
        name = upload.filename or "untitled"
        result: Dict[str, Any] = {"filename": name, "status": "imported", "sources": [], "skipped": [], "passages": 0}
        results.append(result)

        data = await upload.read(MAX_FILE_BYTES + 1)
        try:
            documents, skipped = await run_in_threadpool(extract_file, name, data)
        except ExtractionError as exc:
            result.update(status="failed", detail=str(exc))
            continue
        except Exception as exc:  # a parser crashed on a malformed file
            logger.warning("Could not extract %s: %s", name, exc, exc_info=True)
            result.update(status="failed", detail="could not read this file")
            continue
        result["skipped"] = skipped

        duplicates = 0
        for document in documents:
            content_hash = _content_hash(document)
            existing = await db.scalar(
                select(Source.id).where(Source.project_id == pid, Source.content_hash == content_hash).limit(1)
            )
            if existing:
                duplicates += 1
                continue

            source = Source(
                id=uuid.uuid4(),
                project_id=pid,
                external_id=document.path[:1000],
                title=document.title[:500],
                mime_type=document.mime_type,
                content_hash=content_hash,
            )
            passages = await run_in_threadpool(_passages, document, project_id, source.id, kind)
            if not passages:
                result["skipped"].append({"path": document.path, "reason": "no readable text (a scanned PDF needs OCR first)"})
                continue
            if total_passages + len(passages) > MAX_PASSAGES_PER_REQUEST:
                result["skipped"].append({"path": document.path, "reason": "upload limit reached; add it in a separate upload"})
                continue

            db.add(source)
            await db.flush()
            db.add_all(passages)
            await db.flush()
            total_passages += len(passages)
            result["passages"] += len(passages)
            result["sources"].append(_source_payload(source, len(passages)))

        await db.commit()

        if not result["sources"]:
            if duplicates and duplicates == len(documents):
                result.update(status="duplicate", detail="already in this project")
            elif documents or result["skipped"]:
                reasons = {s["reason"] for s in result["skipped"]}
                result.update(status="skipped", detail="; ".join(sorted(reasons)) or "nothing new to import")
            else:
                result.update(status="skipped", detail="the archive has no supported files")
        elif duplicates:
            result["detail"] = f"{duplicates} file(s) inside were already in this project"

    return {
        "project_id": project_id,
        "files": results,
        "sources_created": sum(len(r["sources"]) for r in results),
        "passages_created": total_passages,
    }


@router.get("", response_model=List[Dict[str, Any]])
async def list_sources(project_id: str, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    """Sources in a project, newest first, with how many passages each one produced."""
    project_id = validate_project_id(project_id)
    await authorize_project(db, project_id, user)
    passages = (
        select(func.count(FeedbackItem.id))
        .where(FeedbackItem.source_id == Source.id)
        .correlate(Source)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            select(Source, passages.label("passages"))
            .where(Source.project_id == project_uuid(project_id))
            .order_by(Source.created_at.desc())
        )
    ).all()
    return [_source_payload(source, count or 0) for source, count in rows]


@router.delete("/{source_id}", response_model=Dict[str, Any])
async def delete_source(source_id: uuid.UUID, project_id: str, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    """Remove a source and its passages from the project. Themes are rebuilt on the next analysis."""
    project_id = validate_project_id(project_id)
    await authorize_project(db, project_id, user)
    source = await db.scalar(select(Source).where(Source.id == source_id, Source.project_id == project_uuid(project_id)))
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found in this project.")
    removed = await db.execute(delete(FeedbackItem).where(FeedbackItem.source_id == source_id))
    await db.execute(delete(Source).where(Source.id == source_id))
    await db.commit()
    return {"deleted": str(source_id), "passages_removed": removed.rowcount or 0}
