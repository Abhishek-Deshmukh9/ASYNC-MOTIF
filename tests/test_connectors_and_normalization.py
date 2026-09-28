import pytest
from app.connectors.base import BaseConnector, RawFeedbackItem
from app.connectors.slack import SlackConnector
from app.connectors.notion import NotionConnector
from app.connectors.google_drive import GoogleDriveConnector
from app.core.normalization import (
    clean_text,
    detect_churn_intent,
    compute_lexical_fingerprint,
    normalize_and_deduplicate,
)


def test_clean_text():
    raw = "  Hello <script>alert(1)</script> <b>world</b>! Visit [our site](https://example.com) now.  "
    cleaned = clean_text(raw)
    assert "<script>" not in cleaned
    assert "<b>" not in cleaned
    assert "our site" in cleaned
    assert "https://" not in cleaned
    assert cleaned == "Hello world! Visit our site now."


def test_detect_churn_intent():
    assert detect_churn_intent("We are cancelling our contract due to this bug.") is True
    assert detect_churn_intent("This is blocking our team completely.") is True
    assert detect_churn_intent("The font is slightly too small on mobile.") is False


def test_slack_privacy_boundary():
    # Only allowed_channel_ids should pass
    slack = SlackConnector(allowed_channel_ids={"C123_PUBLIC"})
    assert slack.is_scope_allowed("C123_PUBLIC", is_private=False) is True
    # DMs and private channels must be blocked
    assert slack.is_scope_allowed("C123_PUBLIC", is_private=True) is False
    assert slack.is_scope_allowed("D999_DIRECT_MESSAGE", is_private=True) is False
    assert slack.is_scope_allowed("C999_OTHER", is_private=False) is False


def test_notion_privacy_boundary():
    notion = NotionConnector(allowed_database_ids={"db_allowed_123"})
    assert notion.is_scope_allowed("db_allowed_123", is_private=False) is True
    assert notion.is_scope_allowed("db_private_456", is_private=True) is False
    assert notion.is_scope_allowed("db_unapproved_789", is_private=False) is False


def test_google_drive_privacy_boundary():
    gdrive = GoogleDriveConnector(allowed_folder_ids={"folder_feedback_docs"})
    assert gdrive.is_scope_allowed("folder_feedback_docs", is_private=False) is True
    assert gdrive.is_scope_allowed("folder_personal_notes", is_private=True) is False
    assert gdrive.is_scope_allowed("folder_unapproved", is_private=False) is False


def test_deduplication_exact_and_near():
    items = [
        {
            "source_type": "app_store",
            "content": "Google SSO tokens expire every 20 minutes and force users to log in again.",
            "customer_id": "cust_1",
            "customer_tier": "starter",
            "arr_value": 1000.0,
        },
        # Exact duplicate
        {
            "source_type": "app_store",
            "content": "Google SSO tokens expire every 20 minutes and force users to log in again.",
            "customer_id": "cust_2",
            "customer_tier": "growth",
            "arr_value": 25000.0,
            "churn_risk_flag": True,
        },
        # Near duplicate with minor suffix
        {
            "source_type": "email",
            "content": "Google SSO tokens expire every 20 minutes and force users to log in again. Please fix!",
            "customer_id": "cust_3",
            "customer_tier": "enterprise",
            "arr_value": 80000.0,
        },
        # Distinct item
        {
            "source_type": "email",
            "content": "CSV export silently truncates reports over 10,000 rows.",
            "customer_id": "cust_4",
            "customer_tier": "enterprise",
            "arr_value": 100000.0,
        },
    ]

    canonical, dupes_count = normalize_and_deduplicate(items)
    assert len(canonical) == 2
    assert dupes_count == 2
    # Check that highest ARR and churn flags were aggregated
    sso_item = [x for x in canonical if "SSO" in x.clean_content][0]
    assert sso_item.duplicate_count == 3
    assert sso_item.arr_value == 80000.0
    assert sso_item.churn_risk_flag is True
