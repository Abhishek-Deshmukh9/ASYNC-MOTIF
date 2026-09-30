"""Projects, connectors, sources and meetings; chunk columns; vector index; row level security.

Revision ID: 003_sources_meetings
Revises: 002_project_scoping
Create Date: 2026-09-30

Every statement is idempotent (IF NOT EXISTS), so this migration is safe on a database
created by scripts/init-db.sql, by the app's create_all(), or by earlier migrations.
"""
import re
from typing import Sequence, Union

from alembic import op

revision: str = "003_sources_meetings"
down_revision: Union[str, None] = "002_project_scoping"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every table the app owns. Row level security is enabled on all of them: on Supabase the
# public schema is reachable through its REST API with the publishable key (which ships to
# the browser), and RLS with no policies blocks that path. The backend connects as the
# tables' owner, which is not subject to RLS, so the app keeps working unchanged.
APP_TABLES = [
    "feedback_items",
    "themes",
    "theme_feedback_associations",
    "approval_audit_log",
    "projects",
    "connections",
    "sources",
    "meetings",
    "meeting_segments",
    "alembic_version",
]

UPGRADE_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid,                                   -- Supabase auth user id (set once login lands)
    name text NOT NULL,
    github_repo text,                                -- owner/repo for issues from this project
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id);

CREATE TABLE IF NOT EXISTS connections (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider varchar(50) NOT NULL,                   -- upload | obsidian | notion | gdrive | slack | meeting
    config jsonb NOT NULL DEFAULT '{}'::jsonb,       -- folder ids, page ids, channel ids
    credentials jsonb,                               -- tokens; server-side only, never returned by the API
    sync_cursor text,
    last_synced_at timestamptz,
    status varchar(50) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_connections_project_id ON connections (project_id);

CREATE TABLE IF NOT EXISTS sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    connection_id uuid REFERENCES connections(id) ON DELETE SET NULL,
    external_id text,                                -- Drive file id, Notion page id, Slack ts ...
    title text,
    url text,
    mime_type varchar(255),
    storage_path text,                               -- original file / audio in object storage
    content_hash varchar(64),                        -- skip re-importing unchanged documents
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_sources_connection_external UNIQUE (connection_id, external_id)
);
CREATE INDEX IF NOT EXISTS ix_sources_project_id ON sources (project_id);

ALTER TABLE feedback_items ADD COLUMN IF NOT EXISTS source_id uuid REFERENCES sources(id) ON DELETE CASCADE;
ALTER TABLE feedback_items ADD COLUMN IF NOT EXISTS chunk_index integer;
ALTER TABLE feedback_items ADD COLUMN IF NOT EXISTS speaker varchar(255);
CREATE INDEX IF NOT EXISTS ix_feedback_items_source_id ON feedback_items (source_id);

-- Nearest-neighbour search on embeddings (theme merging, matching existing issues, dedupe)
CREATE INDEX IF NOT EXISTS ix_feedback_items_embedding_hnsw
    ON feedback_items USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS meetings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title text,
    status varchar(50) NOT NULL DEFAULT 'recording', -- recording | transcribing | done
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    source_id uuid REFERENCES sources(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS ix_meetings_project_id ON meetings (project_id);

CREATE TABLE IF NOT EXISTS meeting_segments (
    meeting_id uuid NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    seq integer NOT NULL,
    text text NOT NULL DEFAULT '',
    start_ms integer,
    end_ms integer,
    speaker varchar(255),
    storage_path text,                               -- this segment's audio in object storage
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (meeting_id, seq)
);
"""


def _statements(sql: str):
    """asyncpg runs one statement per call: drop '--' comments (they may contain ';'), then split on ';'."""
    without_comments = re.sub(r"--[^\n]*", "", sql)
    for chunk in without_comments.split(";"):
        if chunk.strip():
            yield chunk.strip()


def upgrade() -> None:
    for statement in _statements(UPGRADE_SQL):
        op.execute(statement)
    for table in APP_TABLES:
        op.execute(f"ALTER TABLE IF EXISTS {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS meeting_segments")
    op.execute("DROP TABLE IF EXISTS meetings")
    op.execute("DROP INDEX IF EXISTS ix_feedback_items_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_feedback_items_source_id")
    op.execute("ALTER TABLE feedback_items DROP COLUMN IF EXISTS speaker")
    op.execute("ALTER TABLE feedback_items DROP COLUMN IF EXISTS chunk_index")
    op.execute("ALTER TABLE feedback_items DROP COLUMN IF EXISTS source_id")
    op.execute("DROP TABLE IF EXISTS sources")
    op.execute("DROP TABLE IF EXISTS connections")
    op.execute("DROP TABLE IF EXISTS projects")
