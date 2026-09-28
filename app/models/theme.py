import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Numeric, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.models.feedback import theme_feedback_associations


class Theme(Base):
    __tablename__ = "themes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cluster_id = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False)
    revenue_at_risk = Column(Numeric(12, 2), default=0.00)
    affected_accounts_count = Column(Integer, default=0)
    status = Column(
        String(50),
        default="pending_review",
    )  # 'pending_review', 'approved', 'rejected', 'shipped'
    prd_markdown = Column(Text, nullable=True)
    github_issue_url = Column(String(500), nullable=True)
    github_issue_number = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    feedback_items = relationship(
        "FeedbackItem",
        secondary=theme_feedback_associations,
        back_populates="themes",
    )
    audit_logs = relationship(
        "ApprovalAuditLog",
        back_populates="theme",
        cascade="all, delete-orphan",
    )
