"""
Live inbox: send one message to a project and watch it join a theme and move the ranking.

Two ways in:
- the app (POST /inbox), for anyone who can edit the project;
- a secret webhook link per project (POST /inbox/hook/{token}), for Discord bots, Zapier, a support tool or curl.
  Only the project owner can create or turn off the link, and only a hash of it is stored.
"""
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.api.deps import get_db
from app.api.v1.endpoints.pipeline import DEMO_SCOPE, _runs
from app.config import settings
from app.core import live_inbox
from app.core.auth import CurrentUser, get_current_user
from app.core.issue_target import DEMO_READ_ONLY_MESSAGE, demo_is_locked
from app.core.projects import ROLE_RANK, authorize_project, project_uuid, validate_project_id
from app.models.project import Project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inbox", tags=["Live inbox"])
hook_router = APIRouter(prefix="/inbox", tags=["Live inbox"])  # public: the secret link is the credential

MAX_HOOK_BODY_BYTES = 64 * 1024


class InboxPost(BaseModel):
    project_id: Optional[str] = Field(default=None, max_length=255)
    text: str = Field(..., min_length=1, max_length=live_inbox.MAX_TEXT_CHARS)
    author: Optional[str] = Field(default=None, max_length=120)
    source: str = Field(default="other", max_length=40)
    customer: Optional[str] = Field(default=None, max_length=200)
    plan: Optional[str] = Field(default=None, max_length=40)
    arr: Optional[float] = Field(default=None, ge=0, le=1_000_000_000)


def _running(project_id: Optional[str]) -> bool:
    return (_runs.get(project_id or DEMO_SCOPE) or {}).get("status") == "running"


def _hook_path(token: str) -> str:
    return f"{settings.API_V1_PREFIX}/inbox/hook/{token}"


async def _project(db: AsyncSession, project_id: str) -> Project:
    project = await db.scalar(
        select(Project).options(undefer(Project.inbox_token_hash), undefer(Project.inbox_token_hint)).where(Project.id == project_uuid(project_id))
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


@router.get("", response_model=Dict[str, Any])
async def read_inbox(
    project_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """The newest live messages and where each one is now, plus whether the webhook link is on."""
    role = await authorize_project(db, project_id, user)
    live_inbox.warm_model()
    webhook: Dict[str, Any] = {"available": project_id is not None, "enabled": False, "hint": None}
    if project_id is not None:
        project = await db.scalar(select(Project).options(undefer(Project.inbox_token_hint)).where(Project.id == project_uuid(validate_project_id(project_id))))
        if project is not None and project.inbox_token_hint:
            webhook.update(enabled=True, hint=project.inbox_token_hint)
    can_send = (role is None or ROLE_RANK.get(role, 0) >= ROLE_RANK["editor"]) and not demo_is_locked(
        project_id=project_id, signed_in=user is not None, writable=settings.DEMO_WRITABLE
    )
    return {
        "items": await live_inbox.feed(db, project_id),
        "webhook": webhook,
        "sources": live_inbox.SOURCES,
        "threshold": live_inbox.match_threshold(),
        "can_send": can_send,
        "can_manage_webhook": project_id is not None and (role is None or role == "owner"),
        "analysis_running": _running(project_id),
    }


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def send_to_inbox(
    body: InboxPost,
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """Add one message from the app. It joins the closest theme if similar enough, and the project is re-scored."""
    await authorize_project(db, body.project_id, user, need="edit")
    if demo_is_locked(project_id=body.project_id, signed_in=user is not None, writable=settings.DEMO_WRITABLE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEMO_READ_ONLY_MESSAGE)
    message = live_inbox.InboxMessage(
        text=body.text, source=live_inbox.source_key(body.source), author=(body.author or "").strip() or None,
        customer=(body.customer or "").strip() or None, plan=body.plan, arr=body.arr,
    )
    try:
        return await live_inbox.receive(
            db, body.project_id, message, via="app",
            received_by=(user.email or user.id) if user else None, analysis_running=_running(body.project_id),
        )
    except live_inbox.InboxError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.post("/webhook", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_webhook(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """Make (or replace) the project's secret webhook link. The full link is shown once; only its hash is kept."""
    project_id = validate_project_id(project_id)
    await authorize_project(db, project_id, user, need="owner")
    project = await _project(db, project_id)
    token = live_inbox.new_token()
    project.inbox_token_hash = live_inbox.token_hash(token)
    project.inbox_token_hint = token[-4:]
    await db.commit()
    return {"token": token, "path": _hook_path(token), "hint": project.inbox_token_hint}


@router.delete("/webhook", response_model=Dict[str, Any])
async def delete_webhook(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """Turn the webhook link off. Messages sent to the old link are refused."""
    project_id = validate_project_id(project_id)
    await authorize_project(db, project_id, user, need="owner")
    project = await _project(db, project_id)
    project.inbox_token_hash = None
    project.inbox_token_hint = None
    await db.commit()
    return {"enabled": False}


@hook_router.post("/hook/{token}", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def receive_webhook(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """
    For other tools. Body: {"text": "...", "from": "...", "source": "discord", "customer": "...", "plan": "...",
    "arr": 50000, "id": "...", "occurred_at": "..."}, a Discord message object, or {"ticket": {...}}.
    """
    if not token.startswith(live_inbox.TOKEN_PREFIX) or len(token) > 100:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown inbox link.")
    digest = live_inbox.token_hash(token)
    project = await db.scalar(select(Project).where(Project.inbox_token_hash == digest))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown inbox link.")
    if not live_inbox.allow_hook(digest):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=f"At most {live_inbox.HOOK_LIMIT_PER_MINUTE} messages a minute per link.")
    raw = await request.body()
    if len(raw) > MAX_HOOK_BODY_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Send at most 64 KB per message.")
    try:
        body = json.loads(raw.decode("utf-8") or "null")
        message = live_inbox.parse_payload(body)
        project_id = str(project.id)
        return await live_inbox.receive(db, project_id, message, via="webhook", analysis_running=_running(project_id))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The body must be JSON.")
    except live_inbox.InboxError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
