"""Team projects: members invited by email with a role, and the owner's email on each project.

Revision ID: 005_project_members
Revises: 004_theme_scoring
Create Date: 2026-10-01

Idempotent (IF NOT EXISTS) like 003 and 004. Row level security is on, like every other app table:
the backend connects as the table owner, so only the browser-facing REST path is blocked.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "005_project_members"
down_revision: Union[str, None] = "004_theme_scoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_email TEXT")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_members (
            id UUID PRIMARY KEY,
            project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            email TEXT NOT NULL,
            user_id UUID,
            role VARCHAR(20) NOT NULL DEFAULT 'editor',
            invited_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            joined_at TIMESTAMPTZ,
            CONSTRAINT project_members_role CHECK (role IN ('editor', 'viewer')),
            CONSTRAINT project_members_unique_email UNIQUE (project_id, email)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_members_user_id ON project_members (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_members_email ON project_members (email)")
    op.execute("ALTER TABLE project_members ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_members")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS owner_email")
