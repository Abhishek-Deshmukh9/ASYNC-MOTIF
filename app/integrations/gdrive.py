"""
Google Drive through a service account: the person shares a folder with the service account's
email address (Viewer), and Motif reads only that folder. No Google consent screen is needed.
"""
import re
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import jwt

from app.core.extraction import SUPPORTED_TYPES, MAX_FILE_BYTES, extension_of
from app.integrations.base import MAX_DOCS_PER_SYNC, Provider, ProviderError, RemoteDoc, send

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
API = "https://www.googleapis.com/drive/v3"
FOLDER = "application/vnd.google-apps.folder"
DOC, SHEET, SLIDES = "application/vnd.google-apps.document", "application/vnd.google-apps.spreadsheet", "application/vnd.google-apps.presentation"
MAX_DEPTH = 4


def parse_folder_id(value: str) -> str:
    """Accepts a folder link or a bare folder id."""
    value = (value or "").strip()
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", value) or re.search(r"[?&]id=([A-Za-z0-9_-]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", value):
        return value
    raise ProviderError("That does not look like a Google Drive folder link.")


class GoogleDriveProvider(Provider):
    name = "gdrive"
    label = "Google Drive"

    def __init__(self, credentials, transport=None):
        super().__init__(credentials, transport)
        self._token: Optional[str] = None
        self._token_expiry = 0.0

    def _key(self) -> Dict[str, Any]:
        raw = self.credentials.get("service_account")
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except ValueError:
                raise ProviderError("The key is not valid JSON. Paste the whole file you downloaded from Google Cloud.")
        if not isinstance(raw, dict) or not raw.get("client_email") or not raw.get("private_key"):
            raise ProviderError("This is not a service account key. It should contain client_email and private_key.")
        return raw

    async def _access_token(self, client) -> str:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        key = self._key()
        now = int(time.time())
        token_uri = key.get("token_uri") or "https://oauth2.googleapis.com/token"
        try:
            assertion = jwt.encode({"iss": key["client_email"], "scope": SCOPE, "aud": token_uri, "iat": now, "exp": now + 3600}, key["private_key"], algorithm="RS256")
        except Exception:
            raise ProviderError("The private key in this file could not be read. Download a fresh key from Google Cloud.")
        response = await send(client, "POST", token_uri, service="Google", data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
        if response.status_code != 200:
            raise ProviderError("Google did not accept this key. Check that the Drive API is enabled and the key is still active.")
        data = response.json()
        self._token = data["access_token"]
        self._token_expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    async def _get(self, client, path: str, **kwargs):
        token = await self._access_token(client)
        response = await send(client, "GET", f"{API}{path}", service="Google Drive", headers={"Authorization": f"Bearer {token}"}, **kwargs)
        if response.status_code == 404:
            raise ProviderError("Motif cannot see that folder. Share it with the service account email (Viewer).")
        if response.status_code == 403:
            raise ProviderError("Google Drive refused access. Enable the Google Drive API for this project and share the folder with the service account.")
        if response.status_code >= 400:
            raise ProviderError(f"Google Drive returned an error ({response.status_code}).")
        return response

    async def validate(self) -> Dict[str, Any]:
        key = self._key()
        async with self.client() as client:
            await self._access_token(client)
        return {"display_name": key["client_email"], "service_account_email": key["client_email"]}

    async def _list(self, client, folder_id: str) -> List[Dict[str, Any]]:
        files, page_token = [], None
        while True:
            params = {"q": f"'{folder_id}' in parents and trashed = false", "pageSize": 100, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                      "fields": "nextPageToken, files(id, name, mimeType, size, webViewLink)"}
            if page_token:
                params["pageToken"] = page_token
            data = (await self._get(client, "/files", params=params)).json()
            files.extend(data.get("files", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                return files

    async def options(self) -> List[Dict[str, Any]]:
        """Folders that have been shared with the service account."""
        async with self.client() as client:
            params = {"q": f"mimeType = '{FOLDER}' and trashed = false", "pageSize": 50, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true", "fields": "files(id, name)"}
            data = (await self._get(client, "/files", params=params)).json()
        return [{"id": f["id"], "name": f["name"]} for f in data.get("files", [])]

    async def _export(self, client, file: Dict[str, Any]) -> Optional[RemoteDoc]:
        mime, name, fid = file["mimeType"], file["name"], file["id"]
        url = file.get("webViewLink")
        if mime in (DOC, SLIDES):
            for target in (("text/markdown", "text/plain") if mime == DOC else ("text/plain",)):
                response = await send(client, "GET", f"{API}/files/{fid}/export", service="Google Drive", params={"mimeType": target},
                                      headers={"Authorization": f"Bearer {await self._access_token(client)}"})
                if response.status_code == 200:
                    return RemoteDoc(external_id=fid, title=name, url=url, kind="document", text=response.text)
            return None
        if mime == SHEET:
            response = await send(client, "GET", f"{API}/files/{fid}/export", service="Google Drive", params={"mimeType": "text/csv"},
                                  headers={"Authorization": f"Bearer {await self._access_token(client)}"})
            return RemoteDoc(external_id=fid, title=name, url=url, data=response.content, filename=f"{name}.csv") if response.status_code == 200 else None
        if mime.startswith("application/vnd.google-apps"):
            return None
        if extension_of(name) not in SUPPORTED_TYPES or int(file.get("size") or 0) > MAX_FILE_BYTES:
            return None
        response = await self._get(client, f"/files/{fid}", params={"alt": "media", "supportsAllDrives": "true"})
        return RemoteDoc(external_id=fid, title=name, url=url, data=response.content, filename=name)

    async def documents(self, config: Dict[str, Any]) -> AsyncIterator[RemoteDoc]:
        folder_id = parse_folder_id(config.get("folder_id") or config.get("folder_url") or "")
        async with self.client() as client:
            queue = [(folder_id, 0)]
            count = 0
            while queue:
                current, depth = queue.pop(0)
                for file in await self._list(client, current):
                    if file["mimeType"] == FOLDER:
                        if depth < MAX_DEPTH:
                            queue.append((file["id"], depth + 1))
                        continue
                    doc = await self._export(client, file)
                    if doc is None:
                        continue
                    yield doc
                    count += 1
                    if count >= MAX_DOCS_PER_SYNC:
                        return
