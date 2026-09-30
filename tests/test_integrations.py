import asyncio
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import settings
from app.core.secrets import SecretsNotConfigured, decrypt_credentials, encrypt_credentials
from app.integrations import GoogleDriveProvider, NotionProvider, ProviderError, SlackProvider
from app.integrations.gdrive import parse_folder_id
from app.integrations.slack import clean_message


def run(coro):
    return asyncio.run(coro)


async def collect(agen):
    return [item async for item in agen]


def transport(handler):
    return httpx.MockTransport(handler)


# ---------- credentials ----------
def test_credentials_round_trip_and_are_not_plain_text(monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_ENCRYPTION_KEY", "a-long-random-string-for-tests")
    stored = encrypt_credentials({"token": "ntn_secret_value"})
    assert "ntn_secret_value" not in json.dumps(stored)
    assert decrypt_credentials(stored) == {"token": "ntn_secret_value"}
    monkeypatch.setattr(settings, "CONNECTOR_ENCRYPTION_KEY", "a-different-key")
    with pytest.raises(SecretsNotConfigured):
        decrypt_credentials(stored)


def test_credentials_need_a_key(monkeypatch):
    monkeypatch.setattr(settings, "CONNECTOR_ENCRYPTION_KEY", None)
    monkeypatch.setattr(settings, "SUPABASE_SECRET_KEY", None)
    with pytest.raises(SecretsNotConfigured):
        encrypt_credentials({"token": "x"})


# ---------- Notion ----------
def notion_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer good-token"
    path = request.url.path
    if path == "/v1/users/me":
        return httpx.Response(200, json={"name": "Motif", "bot": {"workspace_name": "Acme HQ"}})
    if path == "/v1/search":
        return httpx.Response(200, json={"has_more": False, "results": [
            {"id": "page-1", "url": "https://notion.so/page-1", "archived": False, "properties": {"Name": {"type": "title", "title": [{"plain_text": "Q3 customer calls"}]}}},
            {"id": "page-2", "archived": True, "properties": {"Name": {"type": "title", "title": [{"plain_text": "Old"}]}}},
            {"id": "row-1", "url": "https://notion.so/row-1", "archived": False, "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Export is slow"}]},
                "Feedback": {"type": "rich_text", "rich_text": [{"plain_text": "CSV export times out for large accounts"}]},
                "Tier": {"type": "select", "select": {"name": "enterprise"}}}},
        ]})
    if path == "/v1/blocks/page-1/children":
        return httpx.Response(200, json={"has_more": False, "results": [
            {"id": "b1", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Pain points"}]}},
            {"id": "b2", "type": "bulleted_list_item", "has_children": True, "bulleted_list_item": {"rich_text": [{"plain_text": "Exports are slow"}]}},
            {"id": "b3", "type": "child_page", "child_page": {"title": "Other page"}},
        ]})
    if path == "/v1/blocks/b2/children":
        return httpx.Response(200, json={"has_more": False, "results": [{"id": "b4", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Seen by 3 accounts"}]}}]})
    if path == "/v1/blocks/row-1/children":
        return httpx.Response(200, json={"has_more": False, "results": []})
    return httpx.Response(404, json={})


def test_notion_validates_and_reads_pages():
    provider = NotionProvider({"token": "good-token"}, transport=transport(notion_handler))
    assert run(provider.validate())["display_name"] == "Acme HQ"
    docs = run(collect(provider.documents({})))
    assert [d.title for d in docs] == ["Q3 customer calls", "Export is slow"]  # archived page skipped
    first = docs[0].text
    assert "## Pain points" in first and "- Exports are slow" in first and "Seen by 3 accounts" in first
    assert "Other page" not in first
    assert "**Feedback:** CSV export times out" in docs[1].text and "**Tier:** enterprise" in docs[1].text


def test_notion_page_choice_limits_import():
    provider = NotionProvider({"token": "good-token"}, transport=transport(notion_handler))
    docs = run(collect(provider.documents({"page_ids": ["row-1"]})))
    assert [d.external_id for d in docs] == ["row-1"]


def test_notion_bad_token_has_a_useful_message():
    handler = lambda request: httpx.Response(401, json={})
    with pytest.raises(ProviderError, match="rejected this token"):
        run(NotionProvider({"token": "nope"}, transport=transport(handler)).validate())
    with pytest.raises(ProviderError, match="integration secret"):
        run(NotionProvider({"token": ""}).validate())


# ---------- Google Drive ----------
@pytest.fixture(scope="module")
def service_account():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    public = key.public_key()
    return {"client_email": "motif@proj.iam.gserviceaccount.com", "private_key": pem, "token_uri": "https://oauth2.googleapis.com/token"}, public


def drive_handler(public):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.host == "oauth2.googleapis.com":
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            claims = jwt.decode(form["assertion"].replace("%2E", "."), public, algorithms=["RS256"], audience="https://oauth2.googleapis.com/token")
            assert claims["iss"] == "motif@proj.iam.gserviceaccount.com" and claims["scope"].endswith("drive.readonly")
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer tok"
        path = request.url.path
        q = request.url.params.get("q", "")
        if path == "/drive/v3/files" and "'root-folder' in parents" in q:
            return httpx.Response(200, json={"files": [
                {"id": "d1", "name": "Interview notes", "mimeType": "application/vnd.google-apps.document", "webViewLink": "https://docs.google.com/d1"},
                {"id": "sub", "name": "Old", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "f1", "name": "survey.csv", "mimeType": "text/csv", "size": "60"},
                {"id": "img", "name": "logo.png", "mimeType": "image/png", "size": "10"},
            ]})
        if path == "/drive/v3/files" and "'sub' in parents" in q:
            return httpx.Response(200, json={"files": [{"id": "d2", "name": "Retro", "mimeType": "application/vnd.google-apps.document"}]})
        if path == "/drive/v3/files/d1/export":
            return httpx.Response(200, text="# Interview\nThe onboarding is confusing for new admins.")
        if path == "/drive/v3/files/d2/export":
            return httpx.Response(200, text="Retro notes: billing page is slow.")
        if path == "/drive/v3/files/f1":
            return httpx.Response(200, content=b"feedback,customer\nCannot export reports,Acme\n")
        return httpx.Response(404, json={})
    return handler


def test_drive_reads_a_shared_folder_and_subfolders(service_account):
    creds, public = service_account
    provider = GoogleDriveProvider({"service_account": json.dumps(creds)}, transport=transport(drive_handler(public)))
    assert run(provider.validate())["display_name"] == "motif@proj.iam.gserviceaccount.com"
    docs = run(collect(provider.documents({"folder_id": "root-folder"})))
    names = sorted(d.title for d in docs)
    assert names == ["Interview notes", "Retro", "survey.csv"]  # the .png is ignored
    by_name = {d.title: d for d in docs}
    assert "onboarding is confusing" in by_name["Interview notes"].text
    assert by_name["survey.csv"].data.startswith(b"feedback")


def test_drive_folder_links_and_bad_keys():
    assert parse_folder_id("https://drive.google.com/drive/folders/1AbC_dEf-2GhIjK?usp=sharing") == "1AbC_dEf-2GhIjK"
    assert parse_folder_id("1AbC_dEf-2GhIjKlm") == "1AbC_dEf-2GhIjKlm"
    with pytest.raises(ProviderError):
        parse_folder_id("not a folder")
    with pytest.raises(ProviderError, match="not valid JSON"):
        run(GoogleDriveProvider({"service_account": "{oops"}).validate())
    with pytest.raises(ProviderError, match="not a service account"):
        run(GoogleDriveProvider({"service_account": {"type": "other"}}).validate())


# ---------- Slack ----------
def slack_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer xoxb-good"
    method = request.url.path.rsplit("/", 1)[-1]
    p = request.url.params
    now = time.time()
    if method == "auth.test":
        return httpx.Response(200, json={"ok": True, "team": "Acme"})
    if method == "conversations.list":
        return httpx.Response(200, json={"ok": True, "channels": [{"id": "C1", "name": "feedback", "is_member": True, "num_members": 5}, {"id": "C2", "name": "random", "is_member": True}]})
    if method == "conversations.history":
        if p["channel"] == "C9":
            return httpx.Response(200, json={"ok": False, "error": "not_in_channel"})
        return httpx.Response(200, json={"ok": True, "has_more": False, "messages": [
            {"ts": str(now - 100), "user": "U1", "text": "Reports keep timing out <@U2> &amp; the export is slow", "thread_ts": str(now - 100), "reply_count": 1},
            {"ts": str(now - 200), "subtype": "channel_join", "user": "U2", "text": "joined"},
            {"ts": str(now - 300), "user": "U2", "text": "See <https://example.com/x|the ticket>"},
        ]})
    if method == "conversations.replies":
        return httpx.Response(200, json={"ok": True, "messages": [{"ts": p["ts"], "user": "U1", "text": "root"}, {"ts": str(float(p["ts"]) + 5), "thread_ts": p["ts"], "user": "U2", "text": "Same here"}]})
    if method == "users.info":
        names = {"U1": "Priya", "U2": "Sam"}
        return httpx.Response(200, json={"ok": True, "user": {"profile": {"display_name": names[p["user"]]}}})
    return httpx.Response(200, json={"ok": False, "error": "unknown_method"})


def test_slack_groups_public_channel_messages_by_month():
    provider = SlackProvider({"token": "xoxb-good"}, transport=transport(slack_handler))
    assert run(provider.validate())["display_name"] == "Acme"
    assert [c["name"] for c in run(provider.options())] == ["#feedback", "#random"]
    docs = run(collect(provider.documents({"channel_ids": ["C1"]})))
    text = "\n".join(d.text for d in docs)
    assert all(d.kind == "meeting" and d.external_id.startswith("C1:") for d in docs)
    assert "Priya: Reports keep timing out @Sam & the export is slow" in text
    assert "↳ Sam: Same here" in text
    assert "Sam: See the ticket (https://example.com/x)" in text
    assert "joined" not in text


def test_slack_needs_a_chosen_channel_and_never_reads_others():
    provider = SlackProvider({"token": "xoxb-good"}, transport=transport(slack_handler))
    with pytest.raises(ProviderError, match="at least one channel"):
        run(collect(provider.documents({})))
    with pytest.raises(ProviderError, match="private or no longer exists"):
        run(collect(provider.documents({"channel_ids": ["C-private"]})))


def test_slack_error_codes_are_translated():
    handler = lambda request: httpx.Response(200, json={"ok": False, "error": "invalid_auth"})
    with pytest.raises(ProviderError, match="xoxb-"):
        run(SlackProvider({"token": "bad"}, transport=transport(handler)).validate())
    assert clean_message("hi <@U9>", {}) == "hi @someone"
