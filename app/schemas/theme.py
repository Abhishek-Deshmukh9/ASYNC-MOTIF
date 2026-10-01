from datetime import datetime
from typing import Any, Dict, Optional, List
from uuid import UUID
from pydantic import BaseModel, Field


class CitedQuote(BaseModel):
    quote_text: str
    feedback_item_id: Optional[UUID] = None
    customer_id: Optional[str] = None
    arr_value: Optional[float] = None
    customer_tier: Optional[str] = None
    source_name: Optional[str] = None  # document or note the quote came from


class ThemeBase(BaseModel):
    cluster_id: int
    title: str
    summary: str
    revenue_at_risk: float = 0.0
    affected_accounts_count: int = 0
    status: str = "pending_review"


class ThemeResponse(ThemeBase):
    id: UUID
    prd_markdown: Optional[str] = None
    github_issue_url: Optional[str] = None
    github_issue_number: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    cited_quotes: List[CitedQuote] = Field(default_factory=list)
    priority_score: Optional[float] = None  # 0-100, from the signals in score_breakdown
    score_breakdown: Optional[Dict[str, Any]] = None  # signals, evidence, reasons, verdict (see app/core/scoring.py)
    activity: List[Dict[str, Any]] = Field(default_factory=list)  # who approved, edited or rejected it, newest first
    mention_count: int = 0  # passages grouped into this theme
    source_count: int = 0  # distinct uploaded sources among them (0 for items without a source)

    model_config = {"from_attributes": True}


class ThemeUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    revenue_at_risk: Optional[float] = None
    status: Optional[str] = None


class ThemeApprovalRequest(BaseModel):
    pm_user_id: str = Field(..., description="ID of the PM approving this theme")
    final_title: Optional[str] = None
    final_summary: Optional[str] = None
    github_repo: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=200)
