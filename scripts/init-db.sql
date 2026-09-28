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
