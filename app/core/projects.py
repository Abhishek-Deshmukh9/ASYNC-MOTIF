"""Project identity and ownership."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.models.project import Project, ProjectMember

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
    values = {"id": pid, "name": (name or "").strip()[:200] or "Untitled project", "owner_id": _owner(user), "owner_email": normalize_email(user.email) or None if user else None}
    stmt = insert(Project).values(**values)
    if name and name.strip():
        stmt = stmt.on_conflict_do_update(index_elements=[Project.id], set_={"name": name.strip()[:200]})
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=[Project.id])
    await db.execute(stmt)
    return pid


ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}
NEED_MESSAGE = {
    "edit": "You have view-only access to this project. Ask the owner for edit access.",
    "owner": "Only the project owner can do this.",
}


def normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


async def claim_invites(db: AsyncSession, user: Optional[CurrentUser]) -> None:
    """Invites are made by email; the first time that person signs in, attach their account to them."""
    if user is None or not user.email or _owner(user) is None:
        return
    pending = (await db.scalars(
        select(ProjectMember).where(ProjectMember.email == normalize_email(user.email), ProjectMember.user_id.is_(None))
    )).all()
    for member in pending:
        member.user_id = _owner(user)
        member.joined_at = datetime.now(timezone.utc)
    if pending:
        await db.commit()


async def project_role(db: AsyncSession, project: Project, user: CurrentUser) -> Optional[str]:
    """owner, editor, viewer, or None when this person has no access."""
    uid = _owner(user)
    if uid is not None and project.owner_id == uid:
        return "owner"
    conditions = [ProjectMember.user_id == uid] if uid is not None else []
    if user.email:
        conditions.append(ProjectMember.email == normalize_email(user.email))
    if not conditions:
        return None
    member = await db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, or_(*conditions)))
    if member is None:
        return None
    if member.user_id is None and uid is not None:  # first visit after being invited
        member.user_id = uid
        member.joined_at = datetime.now(timezone.utc)
        await db.commit()
    return member.role


async def authorize_project(db: AsyncSession, project_id: Optional[str], user: Optional[CurrentUser], need: str = "view") -> Optional[str]:
    """
    Make sure the signed-in user may use this project, at the level the action needs:
    "view" (read), "edit" (upload, analyse, approve, reject) or "owner" (members, connected tools, settings).
    Returns the user's role. No-op when auth is off or for the shared demo corpus (project_id None).
    A project nobody has claimed yet is claimed by the caller. Someone with no access gets 404 (the
    project looks like it does not exist); a member without enough access gets 403 saying why.
    """
    if user is None or project_id is None:
        return None
    validate_project_id(project_id)
    owner = _owner(user)
    pid = project_uuid(project_id)
    project = await db.scalar(select(Project).where(Project.id == pid))
    if project is None:
        await db.execute(insert(Project).values(id=pid, name="Untitled project", owner_id=owner, owner_email=normalize_email(user.email) or None).on_conflict_do_nothing(index_elements=[Project.id]))
        await db.commit()
        project = await db.scalar(select(Project).where(Project.id == pid))
    elif project.owner_id is None:
        project.owner_id = owner
        project.owner_email = normalize_email(user.email) or None
        await db.commit()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    if project.owner_id == owner and owner is not None and not project.owner_email and user.email:
        project.owner_email = normalize_email(user.email)  # projects made before owner emails were stored
        await db.commit()
    role = await project_role(db, project, user)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    if ROLE_RANK[role] < ROLE_RANK["editor" if need == "edit" else need if need in ROLE_RANK else "viewer"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NEED_MESSAGE.get(need, "You do not have access to do this."))
    return role
