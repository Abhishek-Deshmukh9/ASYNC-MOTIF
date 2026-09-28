import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class ApprovalAuditLog(Base):
    __tablename__ = "approval_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    theme_id = Column(
        UUID(as_uuid=True),
        ForeignKey("themes.id", ondelete="CASCADE"),
        nullable=False,
    )
    pm_user_id = Column(String(255), nullable=False)
    action = Column(String(50), nullable=False)  # 'approved', 'edited', 'rejected'
    original_title = Column(String(255), nullable=True)
    final_title = Column(String(255), nullable=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    theme = relationship("Theme", back_populates="audit_logs")
