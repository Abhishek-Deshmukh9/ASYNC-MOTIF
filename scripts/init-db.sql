-- Initialize PostgreSQL with pgvector extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Raw and normalized feedback entries
CREATE TABLE IF NOT EXISTS feedback_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type VARCHAR(50) NOT NULL, -- 'app_store', 'email', 'transcript', 'slack', 'notion'
    external_id VARCHAR(255),
    project_id VARCHAR(255), -- workspace the item belongs to; NULL = demo corpus from seed.py
    content TEXT NOT NULL,
    clean_content TEXT NOT NULL,
    customer_id VARCHAR(255),
    customer_tier VARCHAR(50) DEFAULT 'free', -- 'enterprise', 'growth', 'starter', 'free'
    arr_value NUMERIC(12, 2) DEFAULT 0.00,
    churn_risk_flag BOOLEAN DEFAULT FALSE,
    embedding vector(384),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Discovered themes from clustering
CREATE TABLE IF NOT EXISTS themes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id INT NOT NULL,
    project_id VARCHAR(255), -- NULL = themes discovered from the demo corpus
    title VARCHAR(255) NOT NULL,
    summary TEXT NOT NULL,
    revenue_at_risk NUMERIC(12, 2) DEFAULT 0.00,
    affected_accounts_count INT DEFAULT 0,
    status VARCHAR(50) DEFAULT 'pending_review', -- 'pending_review', 'approved', 'rejected', 'shipped'
    prd_markdown TEXT,
    github_issue_url VARCHAR(500),
    github_issue_number INT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_feedback_items_project_id ON feedback_items (project_id);
CREATE INDEX IF NOT EXISTS ix_themes_project_id ON themes (project_id);

-- Association between feedback items and discovered themes
CREATE TABLE IF NOT EXISTS theme_feedback_associations (
    theme_id UUID REFERENCES themes(id) ON DELETE CASCADE,
    feedback_item_id UUID REFERENCES feedback_items(id) ON DELETE CASCADE,
    is_cited_quote BOOLEAN DEFAULT FALSE,
    quote_text TEXT,
    PRIMARY KEY (theme_id, feedback_item_id)
);

-- Audit log for human PM actions
CREATE TABLE IF NOT EXISTS approval_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id UUID REFERENCES themes(id),
    pm_user_id VARCHAR(255) NOT NULL,
    action VARCHAR(50) NOT NULL, -- 'approved', 'edited', 'rejected'
    original_title VARCHAR(255),
    final_title VARCHAR(255),
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Migration 003: projects, connectors, sources, meetings; chunk columns;
-- vector index; row level security (kept in sync with alembic/versions/003_sources_meetings.py)
-- ---------------------------------------------------------------------------
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

-- Row level security: blocks access through Supabase's public REST API; the backend
-- connects as the tables' owner and is not affected.
ALTER TABLE feedback_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE themes ENABLE ROW LEVEL SECURITY;
ALTER TABLE theme_feedback_associations ENABLE ROW LEVEL SECURITY;
ALTER TABLE approval_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE meeting_segments ENABLE ROW LEVEL SECURITY;
