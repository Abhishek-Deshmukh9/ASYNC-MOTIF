"""Notion: read the pages an internal integration has been shared with."""
from typing import Any, AsyncIterator, Dict, List

from app.integrations.base import MAX_DOCS_PER_SYNC, MAX_TEXT_CHARS, Provider, ProviderError, RemoteDoc, send

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
MAX_DEPTH = 3
LISTS = {"bulleted_list_item": "- ", "numbered_list_item": "1. ", "to_do": "- [ ] "}


def rich_text(items: List[Dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in items or [])


def page_title(page: Dict[str, Any]) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return rich_text(prop.get("title")).strip() or "Untitled"
    return "Untitled"


def property_lines(page: Dict[str, Any]) -> List[str]:
    """The readable, non-title properties of a page (for database rows: the feedback columns)."""
    lines = []
    for name, prop in (page.get("properties") or {}).items():
        kind = prop.get("type")
        if kind == "title":
            continue
        if kind == "rich_text":
            value = rich_text(prop.get("rich_text"))
        elif kind in ("select", "status"):
            value = (prop.get(kind) or {}).get("name", "")
        elif kind == "multi_select":
            value = ", ".join(o.get("name", "") for o in prop.get("multi_select") or [])
        elif kind in ("number", "email", "url", "phone_number"):
            value = "" if prop.get(kind) is None else str(prop.get(kind))
        else:
            continue
        if value.strip():
            lines.append(f"**{name}:** {value.strip()}")
    return lines


def block_to_markdown(block: Dict[str, Any], children: str = "") -> str:
    kind = block.get("type", "")
    body = block.get(kind) or {}
    text = rich_text(body.get("rich_text")) if isinstance(body, dict) else ""
    if kind == "heading_1": out = f"# {text}"
    elif kind == "heading_2": out = f"## {text}"
    elif kind == "heading_3": out = f"### {text}"
    elif kind in LISTS:
        prefix = LISTS[kind]
        if kind == "to_do" and body.get("checked"): prefix = "- [x] "
        out = f"{prefix}{text}"
    elif kind == "quote": out = f"> {text}"
    elif kind == "callout": out = f"> {text}"
    elif kind == "code": out = f"```\n{text}\n```"
    elif kind == "divider": out = "---"
    elif kind == "toggle": out = f"**{text}**"
    elif kind in ("paragraph", "bulleted_list_item"): out = text
    elif kind == "bookmark": out = body.get("url", "")
    else: out = text
    if children:
        indented = "\n".join(("  " + line) if line else line for line in children.splitlines())
        out = f"{out}\n{indented}" if out else indented
    return out


class NotionProvider(Provider):
    name = "notion"
    label = "Notion"

    def _headers(self) -> Dict[str, str]:
        token = (self.credentials.get("token") or "").strip()
        if not token:
            raise ProviderError("Paste your Notion integration secret.")
        return {"Authorization": f"Bearer {token}", "Notion-Version": VERSION, "Content-Type": "application/json"}

    async def _call(self, client, method: str, path: str, **kwargs) -> Dict[str, Any]:
        response = await send(client, method, f"{API}{path}", service="Notion", headers=self._headers(), **kwargs)
        if response.status_code == 401:
            raise ProviderError("Notion rejected this token. Copy the integration secret again.")
        if response.status_code == 403:
            raise ProviderError("This Notion integration is not allowed to read content. Turn on 'Read content' for it.")
        if response.status_code == 404:
            raise ProviderError("Notion could not find that page. Share it with the integration (page menu, Connections).")
        if response.status_code >= 400:
            raise ProviderError(f"Notion returned an error ({response.status_code}).")
        return response.json()

    async def validate(self) -> Dict[str, Any]:
        async with self.client() as client:
            me = await self._call(client, "GET", "/users/me")
        workspace = ((me.get("bot") or {}).get("workspace_name")) or me.get("name") or "Notion"
        return {"display_name": workspace}

    async def _pages(self, client, limit: int) -> AsyncIterator[Dict[str, Any]]:
        cursor, seen = None, 0
        while seen < limit:
            body: Dict[str, Any] = {"filter": {"value": "page", "property": "object"}, "page_size": 100,
                                    "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
            if cursor:
                body["start_cursor"] = cursor
            data = await self._call(client, "POST", "/search", json=body)
            for page in data.get("results", []):
                if page.get("archived") or page.get("in_trash"):
                    continue
                seen += 1
                yield page
                if seen >= limit:
                    return
            if not data.get("has_more"):
                return
            cursor = data.get("next_cursor")

    async def options(self) -> List[Dict[str, Any]]:
        async with self.client() as client:
            return [{"id": p["id"], "name": page_title(p)} async for p in self._pages(client, 100)]

    async def _blocks(self, client, block_id: str, depth: int = 0) -> str:
        lines: List[str] = []
        cursor = None
        while True:
            params = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
            data = await self._call(client, "GET", f"/blocks/{block_id}/children", params=params)
            for block in data.get("results", []):
                kind = block.get("type")
                if kind in ("child_page", "child_database", "unsupported"):
                    continue  # other pages are found by search on their own
                if kind == "table":
                    rows = await self._blocks(client, block["id"], depth + 1) if depth < MAX_DEPTH else ""
                    lines.append(rows)
                    continue
                if kind == "table_row":
                    lines.append(" | ".join(rich_text(cell) for cell in (block.get("table_row") or {}).get("cells", [])))
                    continue
                children = ""
                if block.get("has_children") and depth < MAX_DEPTH:
                    children = await self._blocks(client, block["id"], depth + 1)
                rendered = block_to_markdown(block, children)
                if rendered.strip():
                    lines.append(rendered)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
        return "\n".join(lines)

    async def documents(self, config: Dict[str, Any]) -> AsyncIterator[RemoteDoc]:
        wanted = {p.replace("-", "") for p in config.get("page_ids") or []}
        async with self.client() as client:
            count = 0
            async for page in self._pages(client, 500):
                if wanted and page["id"].replace("-", "") not in wanted:
                    continue
                title = page_title(page)
                body = await self._blocks(client, page["id"])
                props = "\n".join(property_lines(page))
                text = "\n\n".join(part for part in (f"# {title}", props, body) if part).strip()[:MAX_TEXT_CHARS]
                if len(text) <= len(title) + 3:
                    continue
                yield RemoteDoc(external_id=page["id"], title=title, url=page.get("url"), kind="note", text=text)
                count += 1
                if count >= MAX_DOCS_PER_SYNC:
                    return
