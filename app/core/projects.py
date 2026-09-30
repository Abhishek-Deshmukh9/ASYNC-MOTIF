"""Project identity and ownership."""
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.models.project import Project

# Project ids that are not UUIDs (older browsers' fallback ids) map to a stable UUID
PROJECT_NAMESPACE = uuid.UUID("6f0f5d4e-8a57-4d0e-9a53-5b7f3c1d2e10")


def project_uuid(project_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(project_id)
    except ValueError:
        return uuid.uuid5(PROJECT_NAMESPACE, project_id)


def validate_project_id(project_id: str) -> str:
    project_id = (project_id or "").strip()
    if not project_id or len(project_id) > 255 or project_id.startswith("__"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A project id is required. The demo benchmark cannot take uploads.")
    return project_id


def _owner(user: Optional[CurrentUser]) -> Optional[uuid.UUID]:
    if user is None:
        return None
    try:
        return uuid.UUID(user.id)
    except ValueError:
        return None


async def ensure_project(db: AsyncSession, project_id: str, name: Optional[str], user: Optional[CurrentUser] = None) -> uuid.UUID:
    pid = project_uuid(project_id)
    values = {"id": pid, "name": (name or "").strip()[:200] or "Untitled project", "owner_id": _owner(user)}
    stmt = insert(Project).values(**values)
    if name and name.strip():
        stmt = stmt.on_conflict_do_update(index_elements=[Project.id], set_={"name": name.strip()[:200]})
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=[Project.id])
    await db.execute(stmt)
    return pid


async def authorize_project(db: AsyncSession, project_id: Optional[str], user: Optional[CurrentUser]) -> None:
    """
    Make sure the signed-in user may use this project. No-op when auth is off or for the shared demo
    corpus (project_id None). A project nobody has claimed yet is claimed by the caller; one owned by
    someone else looks like it does not exist.
    """
    if user is None or project_id is None:
        return
    validate_project_id(project_id)
    owner = _owner(user)
    pid = project_uuid(project_id)
    project = await db.scalar(select(Project).where(Project.id == pid))
    if project is None:
        await db.execute(insert(Project).values(id=pid, name="Untitled project", owner_id=owner).on_conflict_do_nothing(index_elements=[Project.id]))
        await db.commit()
        project = await db.scalar(select(Project).where(Project.id == pid))
    elif project.owner_id is None:
        project.owner_id = owner
        await db.commit()
    if project is None or project.owner_id != owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
