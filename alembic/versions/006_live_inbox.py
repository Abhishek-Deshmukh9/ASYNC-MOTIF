"""Live inbox: a per-project webhook link. Only a hash of the secret link is stored.

Revision ID: 006_live_inbox
Revises: 005_project_members
Create Date: 2026-10-01

Idempotent (IF NOT EXISTS) like 003 to 005. Live messages themselves are ordinary feedback_items
(metadata.live = true), so no new table is needed.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "006_live_inbox"
down_revision: Union[str, None] = "005_project_members"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS inbox_token_hash VARCHAR(64)")
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS inbox_token_hint VARCHAR(12)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_projects_inbox_token_hash ON projects (inbox_token_hash)")
    # The inbox feed reads a project's newest live messages
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_feedback_items_live ON feedback_items (project_id, created_at DESC) "
        "WHERE (metadata->>'live') = 'true'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_feedback_items_live")
    op.execute("DROP INDEX IF EXISTS ux_projects_inbox_token_hash")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS inbox_token_hint")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS inbox_token_hash")
