import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from app.connectors.base import BaseConnector, RawFeedbackItem

logger = logging.getLogger(__name__)


class GoogleDriveConnector(BaseConnector):
    """
    Ingestion connector for designated Google Drive folders (meeting notes, interview docs).
    Enforces strict privacy boundaries: unapproved personal drives or non-whitelisted folders are ignored.
    """

    def __init__(
        self,
        credentials_json: Optional[str] = None,
        allowed_folder_ids: Optional[Set[str]] = None,
    ):
        super().__init__(
            name="GoogleDriveConnector",
            source_type="google_drive",
            allowed_scopes=allowed_folder_ids or set(),
        )
        self.credentials_json = credentials_json

    async def fetch_raw(self) -> List[Dict[str, Any]]:
        """
        List and export document contents from whitelisted Google Drive folders.
        In production, calls Google Drive API v3 files.list and files.export.
        """
        logger.info(f"Scanning allowed Google Drive folders: {self.allowed_scopes}")
        # Stub implementation ready for Google Drive API client integration
        return []

    async def normalize(self, raw_items: List[Dict[str, Any]]) -> List[RawFeedbackItem]:
        """
        Transforms Google Doc / Drive file exports into standardized RawFeedbackItem objects.
        """
        normalized: List[RawFeedbackItem] = []

        for doc in raw_items:
            parent_folder_id = doc.get("parent_folder_id", "")
            is_private = doc.get("is_private", False)

            if not self.is_scope_allowed(parent_folder_id, is_private=is_private):
                logger.debug(f"Skipping Google Drive file outside allowed folder={parent_folder_id}")
                continue

            file_id = doc.get("id", "")
            content = doc.get("content", "").strip()
            if not content:
                continue

            customer_id = doc.get("customer_id")
            customer_email = doc.get("owner_email")
            arr_value = float(doc.get("arr_value", 0.0))
            tier = doc.get("customer_tier", "growth" if arr_value >= 10000 else "free")

            # Parse created or modified timestamp
            time_str = doc.get("modified_time") or doc.get("created_time")
            created_at = (
                datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                if time_str
                else datetime.now(timezone.utc)
            )

            normalized.append(
                RawFeedbackItem(
                    source_type="google_drive",
                    external_id=f"gdrive_{file_id}",
                    content=content,
                    customer_id=customer_id,
                    customer_email=customer_email,
                    customer_tier=tier,
                    arr_value=arr_value,
                    churn_risk_flag=bool(doc.get("churn_risk_flag", False)),
                    created_at=created_at,
                    metadata={
                        "folder_id": parent_folder_id,
                        "file_name": doc.get("name"),
                        "mime_type": doc.get("mime_type"),
                    },
                )
            )

        return normalized
