"""Transparent theme scoring: priority score and per-signal breakdown on themes.

Revision ID: 004_theme_scoring
Revises: 003_sources_meetings
Create Date: 2026-10-01

Idempotent (IF NOT EXISTS) like 003, so it is safe on a database built by create_all().
"""
from typing import Sequence, Union

from alembic import op

revision: str = "004_theme_scoring"
down_revision: Union[str, None] = "003_sources_meetings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE themes ADD COLUMN IF NOT EXISTS priority_score NUMERIC(6, 2)")
    op.execute("ALTER TABLE themes ADD COLUMN IF NOT EXISTS score_breakdown JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE themes DROP COLUMN IF EXISTS score_breakdown")
    op.execute("ALTER TABLE themes DROP COLUMN IF EXISTS priority_score")
