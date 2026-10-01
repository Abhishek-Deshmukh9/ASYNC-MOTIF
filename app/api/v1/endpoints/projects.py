"""The signed-in user's projects (their own and ones shared with them), so they follow the account across devices."""
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.auth import CurrentUser, get_current_user
from app.core.projects import authorize_project, claim_invites, ensure_project, normalize_email, project_uuid, validate_project_id
from app.models.project import Project, ProjectMember

router = APIRouter(prefix="/projects", tags=["Projects"])
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ProjectCreate(BaseModel):
    id: Optional[str] = Field(default=None, max_length=255)
    name: str = Field(min_length=1, max_length=200)
    github_repo: Optional[str] = Field(default=None, max_length=255)

    @field_validator("github_repo")
    @classmethod
    def _repo(cls, v: Optional[str]) -> Optional[str]:
        v = (v or "").strip()
        if v and not REPO_PATTERN.match(v):
            raise ValueError("Use the form owner/repo")
        return v or None


def _payload(p: Project, role: str = "owner") -> Dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "github_repo": p.github_repo,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "role": role,                 # owner | editor | viewer
        "owner_email": p.owner_email,
    }


@router.get("", response_model=List[Dict[str, Any]])
async def list_projects(db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    """Projects the signed-in user owns, then projects shared with them (all projects when sign-in is off)."""
    if user is None:
        return [_payload(p) for p in (await db.scalars(select(Project).order_by(Project.created_at))).all()]
    try:
        uid = uuid.UUID(user.id)
    except ValueError:
        return []
    await claim_invites(db, user)
    owned = (await db.scalars(select(Project).where(Project.owner_id == uid).order_by(Project.created_at))).all()
    match = [ProjectMember.user_id == uid]
    if user.email:
        match.append(ProjectMember.email == normalize_email(user.email))
    shared = (await db.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(or_(*match), Project.owner_id != uid)
        .order_by(Project.created_at)
    )).all()
    return [_payload(p) for p in owned] + [_payload(p, role) for p, role in shared]


@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def save_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db), user: Optional[CurrentUser] = Depends(get_current_user)):
    """Create a project, or rename / re-point an existing one you own."""
    project_id = validate_project_id(payload.id or str(uuid.uuid4()))
    await authorize_project(db, project_id, user, need="owner")
    await ensure_project(db, project_id, payload.name, user)
    project = await db.scalar(select(Project).where(Project.id == project_uuid(project_id)))
    if project is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save the project.")
    project.github_repo = payload.github_repo
    await db.commit()
    await db.refresh(project)
    return _payload(project, "owner")
