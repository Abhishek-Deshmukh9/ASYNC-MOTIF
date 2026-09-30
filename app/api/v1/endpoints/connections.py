"""
Connect outside services (Notion, Google Drive, Slack) to a project and pull their content in as sources.

Credentials are validated with the service, encrypted, and never sent back to the browser.
Each sync adds new documents, refreshes edited ones, and removes documents that are gone.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_db
from app.core.auth import CurrentUser, get_current_user
from app.core.extraction import ExtractedDocument, ExtractionError, extract_file
from app.core.ingest import store_document
from app.core.projects import authorize_project, ensure_project, project_uuid, validate_project_id
from app.core.secrets import SecretsNotConfigured, decrypt_credentials, encrypt_credentials
from app.integrations import PROVIDERS, ProviderError, RemoteDoc
from app.integrations.base import MAX_DOCS_PER_SYNC
from app.models.feedback import FeedbackItem
from app.models.project import Connection, Source

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/connections", tags=["Connections"])

STALE_SYNC = timedelta(minutes=15)


class ConnectionCreate(BaseModel):
    project_id: str = Field(max_length=255)
    project_name: Optional[str] = Field(default=None, max_length=200)
    provider: str
    credentials: Dict[str, Any]
    config: Dict[str, Any] = Field(default_factory=dict)


class ConnectionUpdate(BaseModel):
    config: Dict[str, Any]


def _payload(conn: Connection, sources: int = 0) -> Dict[str, Any]:
    config = dict(conn.config or {})
    return {
        "id": str(conn.id),
        "provider": conn.provider,
        "label": PROVIDERS[conn.provider].label if conn.provider in PROVIDERS else conn.provider,
        "project_id": config.get("project_key") or str(conn.project_id),
        "display_name": config.get("display_name"),
        "config": {k: v for k, v in config.items() if k not in ("project_key", "display_name", "last_error", "last_result")},
        "status": conn.status,
        "last_synced_at": conn.last_synced_at.isoformat() if conn.last_synced_at else None,
        "last_error": config.get("last_error"),
        "last_result": config.get("last_result"),
        "sources": sources,
    }


async def _load(db: AsyncSession, connection_id: uuid.UUID, user: Optional[CurrentUser]) -> Connection:
    conn = await db.scalar(select(Connection).where(Connection.id == connection_id))
    if conn is None or conn.provider not in PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found.")
    await authorize_project(db, (conn.config or {}).get("project_key") or str(conn.project_id), user)
    return conn


def _provider(conn: Connection):
    try:
        return PROVIDERS[conn.provider](decrypt_credentials(conn.credentials or {}))
    except SecretsNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/providers", response_model=List[Dict[str, Any]])
async def list_providers():
    return [{"id": key, "label": cls.label} for key, cls in PROVIDERS.items()]


@router.get("", response_model=List[Dict[str, Any]])
async def list_connections(project_id: str, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    project_id = validate_project_id(project_id)
    await authorize_project(db, project_id, user)
    pid = project_uuid(project_id)
    counts = dict((await db.execute(select(Source.connection_id, func.count(Source.id)).where(Source.project_id == pid, Source.connection_id.isnot(None)).group_by(Source.connection_id))).all())
    conns = (await db.scalars(select(Connection).where(Connection.project_id == pid, Connection.provider.in_(list(PROVIDERS))).order_by(Connection.created_at))).all()
    return [_payload(c, counts.get(c.id, 0)) for c in conns]


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_connection(body: ConnectionCreate, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    if body.provider not in PROVIDERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown service.")
    project_id = validate_project_id(body.project_id)
    await authorize_project(db, project_id, user)
    provider = PROVIDERS[body.provider](body.credentials)
    try:
        info = await provider.validate()
        stored = encrypt_credentials(body.credentials)
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except SecretsNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    pid = await ensure_project(db, project_id, body.project_name, user)
    config = dict(body.config, project_key=project_id, display_name=info.get("display_name"))
    conn = Connection(id=uuid.uuid4(), project_id=pid, provider=body.provider, config=config, credentials=stored, status="active")
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return _payload(conn)


@router.patch("/{connection_id}", response_model=Dict[str, Any])
async def update_connection(connection_id: uuid.UUID, body: ConnectionUpdate, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    """Choose what to import (Notion pages, a Drive folder, Slack channels)."""
    conn = await _load(db, connection_id, user)
    protected = {k: v for k, v in (conn.config or {}).items() if k in ("project_key", "display_name")}
    conn.config = {**{k: v for k, v in body.config.items() if k not in protected}, **protected}
    await db.commit()
    await db.refresh(conn)
    return _payload(conn)


@router.get("/{connection_id}/options", response_model=List[Dict[str, Any]])
async def connection_options(connection_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    conn = await _load(db, connection_id, user)
    try:
        return await _provider(conn).options()
    except ProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _to_documents(remote: RemoteDoc) -> List[ExtractedDocument]:
    if remote.text is not None:
        return [ExtractedDocument(path=remote.external_id, title=remote.title, mime_type="text/markdown", kind="note" if remote.kind == "note" else "document", text=remote.text)]
    documents, _ = extract_file(remote.filename or remote.title, remote.data or b"")
    return documents


@router.post("/{connection_id}/sync", response_model=Dict[str, Any])
async def sync_connection(connection_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    conn = await _load(db, connection_id, user)
    now = datetime.now(timezone.utc)
    if conn.status == "syncing" and conn.last_synced_at is not None and now - conn.last_synced_at < STALE_SYNC:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A sync is already running for this connection.")
    provider = _provider(conn)
    project_key = (conn.config or {}).get("project_key") or str(conn.project_id)
    config = dict(conn.config or {})
    conn.status, conn.last_synced_at = "syncing", now
    await db.commit()

    result = {"imported": 0, "updated": 0, "unchanged": 0, "skipped": 0, "failed": 0, "removed": 0, "passages": 0, "errors": []}
    seen: set = set()
    try:
        async for remote in provider.documents(config):
            try:
                documents = await run_in_threadpool(_to_documents, remote)
            except ExtractionError as exc:
                result["failed"] += 1
                result["errors"].append(f"{remote.title}: {exc}")
                continue
            except Exception:
                logger.warning("Could not read %s", remote.title, exc_info=True)
                result["failed"] += 1
                result["errors"].append(f"{remote.title}: could not read this file")
                continue
            for document in documents:
                external_id = remote.external_id if len(documents) == 1 else f"{remote.external_id}/{document.path}"
                seen.add(external_id)
                outcome = await store_document(db, conn.project_id, project_key, document, remote.kind, connection_id=conn.id, external_id=external_id, url=remote.url, provider=conn.provider)
                await db.commit()
                result[outcome["status"]] += 1
                result["passages"] += outcome["passages"]
        if len(seen) < MAX_DOCS_PER_SYNC:
            gone = (await db.scalars(select(Source).where(Source.connection_id == conn.id, Source.external_id.notin_(seen or {""})))).all()
            for source in gone:
                await db.execute(delete(FeedbackItem).where(FeedbackItem.source_id == source.id))
                await db.execute(delete(Source).where(Source.id == source.id))
                result["removed"] += 1
        conn.status = "active"
        conn.config = {**config, "last_error": None, "last_result": {k: v for k, v in result.items() if k != "errors"}}
    except ProviderError as exc:
        conn.status = "error"
        conn.config = {**config, "last_error": str(exc)}
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        conn.status = "error"
        conn.config = {**config, "last_error": "The sync stopped unexpectedly. Try again."}
        await db.commit()
        logger.error("Sync failed for connection %s", connection_id, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="The sync stopped unexpectedly. Try again.")
    conn.last_synced_at = datetime.now(timezone.utc)
    await db.commit()
    result["errors"] = result["errors"][:5]
    return result


@router.delete("/{connection_id}", response_model=Dict[str, Any])
async def delete_connection(connection_id: uuid.UUID, remove_sources: bool = False, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    """Disconnect. The imported sources stay in the project unless remove_sources=true."""
    conn = await _load(db, connection_id, user)
    removed = 0
    ids = (await db.scalars(select(Source.id).where(Source.connection_id == conn.id))).all()
    if remove_sources and ids:
        await db.execute(delete(FeedbackItem).where(FeedbackItem.source_id.in_(ids)))
        await db.execute(delete(Source).where(Source.id.in_(ids)))
        removed = len(ids)
    await db.execute(delete(Connection).where(Connection.id == conn.id))
    await db.commit()
    return {"deleted": str(connection_id), "sources_removed": removed}
