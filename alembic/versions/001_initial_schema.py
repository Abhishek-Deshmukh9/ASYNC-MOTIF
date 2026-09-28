"""Initial schema with pgvector

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-09-28 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Ensure uuid-ossp and vector extensions are installed
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector";')

    # 2. Create feedback_items table
    op.create_table(
        'feedback_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('source_type', sa.String(length=50), nullable=False),
        sa.Column('external_id', sa.String(length=255), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('clean_content', sa.Text(), nullable=False),
        sa.Column('customer_id', sa.String(length=255), nullable=True),
        sa.Column('customer_tier', sa.String(length=50), server_default='free', nullable=True),
        sa.Column('arr_value', sa.Numeric(precision=12, scale=2), server_default='0.00', nullable=True),
        sa.Column('churn_risk_flag', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('embedding', Vector(384), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True),
    )

    # 3. Create themes table
    op.create_table(
        'themes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('cluster_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('revenue_at_risk', sa.Numeric(precision=12, scale=2), server_default='0.00', nullable=True),
        sa.Column('affected_accounts_count', sa.Integer(), server_default='0', nullable=True),
        sa.Column('status', sa.String(length=50), server_default='pending_review', nullable=True),
        sa.Column('prd_markdown', sa.Text(), nullable=True),
        sa.Column('github_issue_url', sa.String(length=500), nullable=True),
        sa.Column('github_issue_number', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )

    # 4. Create theme_feedback_associations table
    op.create_table(
        'theme_feedback_associations',
        sa.Column('theme_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('themes.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('feedback_item_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('feedback_items.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('is_cited_quote', sa.Boolean(), server_default='false', nullable=True),
        sa.Column('quote_text', sa.Text(), nullable=True),
    )

    # 5. Create approval_audit_log table
    op.create_table(
        'approval_audit_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('theme_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('themes.id', ondelete='CASCADE'), nullable=False),
        sa.Column('pm_user_id', sa.String(length=255), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('original_title', sa.String(length=255), nullable=True),
        sa.Column('final_title', sa.String(length=255), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('approval_audit_log')
    op.drop_table('theme_feedback_associations')
    op.drop_table('themes')
    op.drop_table('feedback_items')
