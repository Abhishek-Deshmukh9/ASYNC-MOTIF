import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from app.connectors.base import BaseConnector, RawFeedbackItem

logger = logging.getLogger(__name__)


class SlackConnector(BaseConnector):
    """
    Ingestion connector for designated public Slack channels.
    Enforces strict privacy boundaries: DMs and non-whitelisted channels are rejected.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        allowed_channel_ids: Optional[Set[str]] = None,
    ):
        super().__init__(
            name="SlackConnector",
            source_type="slack",
            allowed_scopes=allowed_channel_ids or set(),
        )
        self.bot_token = bot_token

    async def fetch_raw(self) -> List[Dict[str, Any]]:
        """
        Fetch conversation messages from whitelisted Slack channels.
        In production, calls Slack WebClient conversations.history.
        """
        logger.info(f"Fetching messages for allowed Slack channels: {self.allowed_scopes}")
        # Stub implementation ready for Slack SDK integration
        return []

    async def normalize(self, raw_items: List[Dict[str, Any]]) -> List[RawFeedbackItem]:
        """
        Filters out private messages and formats message items into RawFeedbackItem.
        """
        normalized: List[RawFeedbackItem] = []

        for item in raw_items:
            channel_id = item.get("channel_id", "")
            is_im = item.get("is_im", False)
            is_private = item.get("is_private", False) or is_im

            # Privacy boundary enforcement
            if not self.is_scope_allowed(channel_id, is_private=is_private):
                logger.debug(f"Skipping out-of-scope Slack message from channel={channel_id}, private={is_private}")
                continue

            text = item.get("text", "").strip()
            if not text:
                continue

            # Timestamp parsing
            ts = item.get("ts")
            created_at = (
                datetime.fromtimestamp(float(ts), tz=timezone.utc)
                if ts
                else datetime.now(timezone.utc)
            )

            # Customer metadata extraction
            user_id = item.get("user")
            user_email = item.get("user_email")
            arr_value = float(item.get("customer_arr", 0.0))
            tier = item.get("customer_tier", "growth" if arr_value > 0 else "free")

            normalized.append(
                RawFeedbackItem(
                    source_type="slack",
                    external_id=f"slack_{channel_id}_{ts or item.get('id', '')}",
                    content=text,
                    customer_id=user_id,
                    customer_email=user_email,
                    customer_tier=tier,
                    arr_value=arr_value,
                    churn_risk_flag=bool(item.get("churn_risk_flag", False)),
                    created_at=created_at,
                    metadata={
                        "channel_id": channel_id,
                        "thread_ts": item.get("thread_ts"),
                        "reactions": item.get("reactions", []),
                    },
                )
            )

        return normalized
