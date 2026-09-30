"""Shared pieces for connectors that pull documents from another service."""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

MAX_DOCS_PER_SYNC = 200
MAX_TEXT_CHARS = 300_000


class ProviderError(Exception):
    """A problem worth showing to the person: bad token, missing access, service down."""


@dataclass
class RemoteDoc:
    external_id: str
    title: str
    url: Optional[str] = None
    kind: str = "document"          # document | note | meeting
    text: Optional[str] = None      # already-readable text (Markdown)
    data: Optional[bytes] = None    # a file to run through the file extractor
    filename: Optional[str] = None  # name with extension, for `data`


class Provider(ABC):
    name = ""
    label = ""

    def __init__(self, credentials: Dict[str, Any], transport: Optional[httpx.AsyncBaseTransport] = None):
        self.credentials = credentials
        self._transport = transport

    def client(self, **kwargs: Any) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=30.0, transport=self._transport, **kwargs)

    @abstractmethod
    async def validate(self) -> Dict[str, Any]:
        """Check the credentials. Returns a display name for the connection; raises ProviderError."""

    @abstractmethod
    async def options(self) -> List[Dict[str, Any]]:
        """What the person can choose to import: pages, folders or channels."""

    @abstractmethod
    def documents(self, config: Dict[str, Any]) -> AsyncIterator[RemoteDoc]:
        """Yield the documents to import for a saved configuration."""


async def send(client: httpx.AsyncClient, method: str, url: str, *, service: str, **kwargs: Any) -> httpx.Response:
    """One request with a few retries for rate limits and brief outages."""
    last: Optional[Exception] = None
    for attempt in range(4):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            last = exc
            await asyncio.sleep(0.5 * (attempt + 1))
            continue
        if response.status_code == 429 or response.status_code >= 500:
            wait = min(float(response.headers.get("Retry-After", 1) or 1), 10.0)
            last = ProviderError(f"{service} is busy (HTTP {response.status_code}).")
            await asyncio.sleep(wait if response.status_code == 429 else 0.5 * (attempt + 1))
            continue
        return response
    raise ProviderError(f"Could not reach {service}. {last}")
