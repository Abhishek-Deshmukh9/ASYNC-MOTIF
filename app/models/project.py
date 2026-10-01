"""Projects, their connected sources, and recorded meetings (schema from migration 003)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base


def _now():
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # Supabase auth user id
    name = Column(Text, nullable=False)
    github_repo = Column(Text, nullable=True)
    owner_email = Column(Text, nullable=True)  # shown to teammates (migration 005)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class ProjectMember(Base):
    """A teammate invited to a project by email. user_id is filled in when they first sign in (migration 005)."""
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "email", name="project_members_unique_email"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(Text, nullable=False)  # stored lower-case
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    role = Column(String(20), nullable=False, default="editor")  # editor | viewer (the owner lives on projects.owner_id)
    invited_by = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    joined_at = Column(DateTime(timezone=True), nullable=True)


class Connection(Base):
    """One plugged-in source for a project: an upload channel, a Notion workspace, a Drive folder..."""
    __tablename__ = "connections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(50), nullable=False)  # upload | obsidian | notion | gdrive | slack | meeting
    config = Column(JSONB, nullable=False, default=dict)
    credentials = Column(JSONB, nullable=True)  # server-side only; never serialise to clients
    sync_cursor = Column(Text, nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class Source(Base):
    """One document, page, channel export or meeting; its text is stored as chunks in feedback_items."""
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("connection_id", "external_id", name="uq_sources_connection_external"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("connections.id", ondelete="SET NULL"), nullable=True)
    external_id = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    url = Column(Text, nullable=True)
    mime_type = Column(String(255), nullable=True)
    storage_path = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="recording")  # recording | transcribing | done
    started_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True)


class MeetingSegment(Base):
    __tablename__ = "meeting_segments"

    meeting_id = Column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), primary_key=True)
    seq = Column(Integer, primary_key=True)
    text = Column(Text, nullable=False, default="")
    start_ms = Column(Integer, nullable=True)
    end_ms = Column(Integer, nullable=True)
    speaker = Column(String(255), nullable=True)
    storage_path = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
