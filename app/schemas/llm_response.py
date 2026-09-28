from typing import List, Optional
from pydantic import BaseModel, Field


class ClusterSynthesizedTheme(BaseModel):
    """Structured theme representation synthesized by LLM with strict quote grounding."""
    title: str = Field(
        ...,
        description="Concise, action-oriented product theme title (e.g., 'Google Workspace SSO Token Desync on 20-Min Expiry')",
        max_length=200,
    )
    problem_statement: str = Field(
        ...,
        description="Objective summary of customer friction, root cause, and technical blockers identified in the cluster.",
    )
    affected_workflows: List[str] = Field(
        default_factory=list,
        description="Specific user journeys or product workflows interrupted (e.g. ['Draft pull request saving', 'Field agent inspection logs'])",
    )
    cited_quotes: List[str] = Field(
        ...,
        description="Exact verbatim substrings from the source customer quotes justifying this theme. Must NOT be paraphrased.",
        min_length=1,
    )
    confidence_score: float = Field(
        default=0.90,
        description="Model confidence in thematic coherence between 0.0 and 1.0",
        ge=0.0,
        le=1.0,
    )
