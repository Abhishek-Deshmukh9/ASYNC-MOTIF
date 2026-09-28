import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from app.connectors.base import BaseConnector, RawFeedbackItem

logger = logging.getLogger(__name__)


class NotionConnector(BaseConnector):
    """
    Ingestion connector for designated Notion feedback databases and pages.
    Enforces strict privacy boundaries: unapproved workspaces or private user pages are ignored.
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        allowed_database_ids: Optional[Set[str]] = None,
    ):
        super().__init__(
            name="NotionConnector",
            source_type="notion",
            allowed_scopes=allowed_database_ids or set(),
        )
        self.api_token = api_token

    async def fetch_raw(self) -> List[Dict[str, Any]]:
        """
        Query designated Notion databases via Notion API.
        In production, calls notion_client databases.query.
        """
        logger.info(f"Querying allowed Notion databases: {self.allowed_scopes}")
        # Stub implementation ready for Notion API client integration
        return []

    async def normalize(self, raw_items: List[Dict[str, Any]]) -> List[RawFeedbackItem]:
        """
        Transforms Notion page records into standardized RawFeedbackItem objects.
        """
        normalized: List[RawFeedbackItem] = []

        for page in raw_items:
            parent_db = page.get("parent_database_id", "")
            is_private = page.get("is_private", False)

            if not self.is_scope_allowed(parent_db, is_private=is_private):
                logger.debug(f"Skipping Notion page outside designated database={parent_db}")
                continue

            page_id = page.get("id", "")
            properties = page.get("properties", {})

            # Extract title and body text blocks
            title = page.get("title", "")
            body = page.get("body", "")
            content = f"{title}\n{body}".strip() if title else body.strip()

            if not content:
                continue

            customer_id = properties.get("customer_id") or page.get("customer_id")
            customer_email = properties.get("customer_email") or page.get("customer_email")
            arr_value = float(properties.get("arr_value", page.get("arr_value", 0.0)))
            tier = properties.get("customer_tier", page.get("customer_tier", "starter"))

            # Parse created timestamp
            created_time_str = page.get("created_time")
            created_at = (
                datetime.fromisoformat(created_time_str.replace("Z", "+00:00"))
                if created_time_str
                else datetime.now(timezone.utc)
            )

            normalized.append(
                RawFeedbackItem(
                    source_type="notion",
                    external_id=f"notion_{page_id}",
                    content=content,
                    customer_id=customer_id,
                    customer_email=customer_email,
                    customer_tier=tier,
                    arr_value=arr_value,
                    churn_risk_flag=bool(properties.get("churn_risk_flag", False)),
                    created_at=created_at,
                    metadata={
                        "database_id": parent_db,
                        "url": page.get("url"),
                        "last_edited_time": page.get("last_edited_time"),
                    },
                )
            )

        return normalized
