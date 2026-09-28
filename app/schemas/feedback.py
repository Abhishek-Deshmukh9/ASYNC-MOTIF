from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID
from pydantic import BaseModel, Field


class FeedbackItemBase(BaseModel):
    source_type: str = Field(..., description="Source system e.g. 'app_store', 'email', 'transcript'")
    external_id: Optional[str] = None
    content: str = Field(..., description="Raw feedback text")
    clean_content: Optional[str] = None
    customer_id: Optional[str] = None
    customer_tier: str = Field(default="free", description="'enterprise', 'growth', 'starter', 'free'")
    arr_value: float = Field(default=0.0, description="Annual recurring revenue value")
    churn_risk_flag: bool = Field(default=False, description="Flag indicating explicit churn intent")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FeedbackItemCreate(FeedbackItemBase):
    pass


class FeedbackItemResponse(FeedbackItemBase):
    id: UUID
    clean_content: str
    created_at: datetime

    model_config = {"from_attributes": True}
