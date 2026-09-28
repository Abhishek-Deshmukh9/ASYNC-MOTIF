import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    Column,
    String,
    Text,
    Numeric,
    Boolean,
    DateTime,
    ForeignKey,
    Table,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from app.db.base import Base

# Association table between themes and feedback items
theme_feedback_associations = Table(
    "theme_feedback_associations",
    Base.metadata,
    Column(
        "theme_id",
        UUID(as_uuid=True),
        ForeignKey("themes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "feedback_item_id",
        UUID(as_uuid=True),
        ForeignKey("feedback_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("is_cited_quote", Boolean, default=False),
    Column("quote_text", Text, nullable=True),
)


class FeedbackItem(Base):
    __tablename__ = "feedback_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type = Column(String(50), nullable=False)  # 'app_store', 'email', 'transcript', 'slack', 'notion'
    external_id = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)
    clean_content = Column(Text, nullable=False)
    customer_id = Column(String(255), nullable=True)
    customer_tier = Column(String(50), default="free")  # 'enterprise', 'growth', 'starter', 'free'
    arr_value = Column(Numeric(12, 2), default=0.00)
    churn_risk_flag = Column(Boolean, default=False)
    embedding = Column(Vector(384), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    metadata_ = Column("metadata", JSONB, default=dict)

    # Relationships
    themes = relationship(
        "Theme",
        secondary=theme_feedback_associations,
        back_populates="feedback_items",
    )
