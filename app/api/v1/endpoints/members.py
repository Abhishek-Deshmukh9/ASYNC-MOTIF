"""Who can work on a project: the owner invites teammates by email as editors or viewers."""
import re
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.auth import CurrentUser, get_current_user
from app.core.projects import authorize_project, normalize_email, project_uuid
from app.models.project import Project, ProjectMember

router = APIRouter(prefix="/projects/{project_id}/members", tags=["Members"])
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ROLES = ("editor", "viewer")


class Invite(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = "editor"

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = normalize_email(value)
        if not EMAIL.match(value):
            raise ValueError("Enter a valid email address")
        return value

    @field_validator("role")
    @classmethod
    def _role(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError("Role must be editor or viewer")
        return value


class RoleChange(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, value: str) -> str:
        if value not in ROLES:
            raise ValueError("Role must be editor or viewer")
        return value


def _member(m: ProjectMember) -> Dict[str, Any]:
    return {
        "id": str(m.id),
        "email": m.email,
        "role": m.role,
        "status": "joined" if m.user_id else "invited",
        "invited_by": m.invited_by,
        "joined_at": m.joined_at.isoformat() if m.joined_at else None,
    }


async def _project(db: AsyncSession, project_id: str) -> Project:
    project = await db.scalar(select(Project).where(Project.id == project_uuid(project_id)))
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


async def _find(db: AsyncSession, project: Project, member_id: uuid.UUID) -> ProjectMember:
    member = await db.scalar(select(ProjectMember).where(ProjectMember.id == member_id, ProjectMember.project_id == project.id))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That person is not on this project.")
    return member


@router.get("", response_model=Dict[str, Any])
async def list_members(project_id: str, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    """Everyone on the project, with the caller's own role. Any member can see the list."""
    role = await authorize_project(db, project_id, user)
    project = await _project(db, project_id)
    members = (await db.scalars(select(ProjectMember).where(ProjectMember.project_id == project.id).order_by(ProjectMember.created_at))).all()
    return {"owner_email": project.owner_email, "my_role": role or "owner", "members": [_member(m) for m in members]}


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def invite_member(project_id: str, body: Invite, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    """Owner only. The project appears for the invitee the next time they sign in with this email."""
    await authorize_project(db, project_id, user, need="owner")
    project = await _project(db, project_id)
    if project.owner_email and body.email == project.owner_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That is the owner's own email.")
    existing = await db.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.email == body.email))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{body.email} is already on this project.")
    member = ProjectMember(
        id=uuid.uuid4(), project_id=project.id, email=body.email, role=body.role,
        invited_by=(user.email or user.id) if user else None,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return _member(member)


@router.patch("/{member_id}", response_model=Dict[str, Any])
async def change_role(project_id: str, member_id: uuid.UUID, body: RoleChange, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    """Owner only: switch a teammate between editor and viewer."""
    await authorize_project(db, project_id, user, need="owner")
    member = await _find(db, await _project(db, project_id), member_id)
    member.role = body.role
    await db.commit()
    await db.refresh(member)
    return _member(member)


@router.delete("/{member_id}", response_model=Dict[str, Any])
async def remove_member(project_id: str, member_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    """The owner can remove anyone; a member can remove themselves (leave the project)."""
    role = await authorize_project(db, project_id, user)
    member = await _find(db, await _project(db, project_id), member_id)
    leaving = user is not None and (
        (member.user_id is not None and str(member.user_id) == user.id) or member.email == normalize_email(user.email)
    )
    if role not in (None, "owner") and not leaving:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the project owner can remove other people.")
    await db.delete(member)
    await db.commit()
    return {"removed": True, "id": str(member_id), "left": leaving}
