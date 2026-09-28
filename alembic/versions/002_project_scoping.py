"""Add project scoping to feedback and discovered themes.

Revision ID: 002_project_scoping
Revises: 001_initial_schema
Create Date: 2026-09-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "002_project_scoping"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS also supports databases initialized previously via
    # SQLAlchemy create_all(), which creates the latest model columns itself.
    op.execute("ALTER TABLE feedback_items ADD COLUMN IF NOT EXISTS project_id VARCHAR(255)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_items_project_id ON feedback_items (project_id)")
    op.execute("ALTER TABLE themes ADD COLUMN IF NOT EXISTS project_id VARCHAR(255)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_themes_project_id ON themes (project_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_themes_project_id")
    op.execute("ALTER TABLE themes DROP COLUMN IF EXISTS project_id")
    op.execute("DROP INDEX IF EXISTS ix_feedback_items_project_id")
    op.execute("ALTER TABLE feedback_items DROP COLUMN IF EXISTS project_id")
