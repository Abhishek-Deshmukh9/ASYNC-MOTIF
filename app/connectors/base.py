from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field


class RawFeedbackItem(BaseModel):
    """Normalized payload produced by connectors before deduplication & embedding."""
    source_type: str = Field(..., description="Source system e.g. 'slack', 'notion', 'google_drive', 'app_store', 'email', 'transcript'")
    external_id: Optional[str] = Field(None, description="Native identifier in the source system")
    content: str = Field(..., description="Original raw feedback body text")
    customer_id: Optional[str] = Field(None, description="Associated customer or user identifier")
    customer_email: Optional[str] = Field(None, description="Sender or customer email if present")
    customer_tier: str = Field(default="free", description="Customer tier: 'enterprise', 'growth', 'starter', 'free'")
    arr_value: float = Field(default=0.0, description="Annual recurring revenue value in USD")
    churn_risk_flag: bool = Field(default=False, description="Heuristic flag for urgent churn indications")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary source-specific metadata")


class BaseConnector(ABC):
    """
    Abstract base connector enforcing:
    1. Standardized ingestion method signature: fetch_and_normalize() -> List[RawFeedbackItem]
    2. Strict Opt-In Privacy Boundary: Discards DMs, private channels, and unselected folder trees.
    """

    def __init__(self, name: str, source_type: str, allowed_scopes: Optional[Set[str]] = None):
        self.name = name
        self.source_type = source_type
        # Whitelist of allowed channel IDs, database IDs, or folder IDs
        self.allowed_scopes: Set[str] = allowed_scopes or set()

    def is_scope_allowed(self, scope_id: str, is_private: bool = False) -> bool:
        """
        Enforce Rule 1.5 (Strict Privacy & Opt-In Scoping):
        Personal DMs, unapproved private channels, and unselected directories must be blocked
        at the ingestion layer and discarded in-memory immediately.
        """
        if is_private:
            return False
        if not self.allowed_scopes:
            # If no scopes specified, connector allows nothing by default (fail-safe)
            return False
        return scope_id in self.allowed_scopes

    @abstractmethod
    async def fetch_raw(self) -> List[Dict[str, Any]]:
        """Fetch raw messages or documents from the target source."""
        pass

    @abstractmethod
    async def normalize(self, raw_items: List[Dict[str, Any]]) -> List[RawFeedbackItem]:
        """Convert raw items into standardized RawFeedbackItem models."""
        pass

    async def fetch_and_normalize(self) -> List[RawFeedbackItem]:
        """Orchestrate fetching, privacy boundary filtering, and normalization."""
        raw_items = await self.fetch_raw()
        return await self.normalize(raw_items)
