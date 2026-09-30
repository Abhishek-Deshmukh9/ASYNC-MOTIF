"""Slack: read the public channels a person picks, using a bot token. Private channels and DMs are never read."""
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List

from app.integrations.base import MAX_TEXT_CHARS, Provider, ProviderError, RemoteDoc, send

API = "https://slack.com/api"
HISTORY_DAYS = 90
MAX_MESSAGES_PER_CHANNEL = 3000
SKIP_SUBTYPES = {"channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name", "bot_add", "bot_remove", "pinned_item"}

ERRORS = {
    "invalid_auth": "Slack rejected this token. Copy the Bot User OAuth Token (starts with xoxb-).",
    "not_authed": "Paste the Bot User OAuth Token (starts with xoxb-).",
    "token_revoked": "This Slack token was revoked. Create a new one.",
    "missing_scope": "The Slack app is missing a permission. Add channels:read, channels:history and users:read, then reinstall it.",
    "not_in_channel": "The Motif bot is not in that channel. In Slack, type /invite @Motif in the channel.",
    "channel_not_found": "Slack could not find that channel.",
    "ratelimited": "Slack is rate limiting requests. Try again in a minute.",
}


def clean_message(text: str, names: Dict[str, str]) -> str:
    text = re.sub(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>", lambda m: "@" + names.get(m.group(1), "someone"), text or "")
    text = re.sub(r"<#[A-Z0-9]+\|([^>]+)>", r"#\1", text)
    text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 (\1)", text)
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return " ".join(text.split())


class SlackProvider(Provider):
    name = "slack"
    label = "Slack"

    async def _call(self, client, method: str, **params) -> Dict[str, Any]:
        token = (self.credentials.get("token") or "").strip()
        if not token:
            raise ProviderError(ERRORS["not_authed"])
        response = await send(client, "GET", f"{API}/{method}", service="Slack", params=params, headers={"Authorization": f"Bearer {token}"})
        data = response.json()
        if not data.get("ok"):
            code = data.get("error", "unknown_error")
            raise ProviderError(ERRORS.get(code, f"Slack returned an error: {code}."))
        return data

    async def validate(self) -> Dict[str, Any]:
        async with self.client() as client:
            info = await self._call(client, "auth.test")
        return {"display_name": info.get("team") or "Slack"}

    async def options(self) -> List[Dict[str, Any]]:
        channels, cursor = [], ""
        async with self.client() as client:
            while True:
                data = await self._call(client, "conversations.list", types="public_channel", exclude_archived="true", limit=200, cursor=cursor)
                channels += [{"id": c["id"], "name": "#" + c["name"], "is_member": bool(c.get("is_member")), "members": c.get("num_members")} for c in data.get("channels", [])]
                cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
                if not cursor:
                    return channels

    async def _username(self, client, cache: Dict[str, str], user_id: str) -> str:
        if user_id not in cache:
            try:
                info = await self._call(client, "users.info", user=user_id)
                profile = (info.get("user") or {}).get("profile") or {}
                cache[user_id] = (profile.get("display_name") or profile.get("real_name") or user_id).strip() or user_id
            except ProviderError:
                cache[user_id] = user_id
        return cache[user_id]

    async def _messages(self, client, channel_id: str) -> List[Dict[str, Any]]:
        oldest = str(time.time() - HISTORY_DAYS * 86400)
        messages, cursor = [], ""
        while len(messages) < MAX_MESSAGES_PER_CHANNEL:
            try:
                data = await self._call(client, "conversations.history", channel=channel_id, oldest=oldest, limit=200, cursor=cursor)
            except ProviderError as exc:
                if "not in that channel" in str(exc):  # try to join public channels on our own
                    try:
                        await self._call(client, "conversations.join", channel=channel_id)
                        continue
                    except ProviderError:
                        pass
                raise
            for message in data.get("messages", []):
                messages.append(message)
                if message.get("reply_count") and message.get("thread_ts") == message.get("ts"):
                    replies = await self._call(client, "conversations.replies", channel=channel_id, ts=message["ts"], limit=200)
                    messages.extend(m for m in replies.get("messages", []) if m.get("ts") != message["ts"])
            cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
            if not data.get("has_more") or not cursor:
                break
        return messages

    async def documents(self, config: Dict[str, Any]) -> AsyncIterator[RemoteDoc]:
        channel_ids = config.get("channel_ids") or []
        if not channel_ids:
            raise ProviderError("Choose at least one channel. Motif reads only the channels you pick.")
        names = {c["id"]: c["name"] for c in await self.options()}
        users: Dict[str, str] = {}
        async with self.client() as client:
            for channel_id in channel_ids:
                if channel_id not in names:
                    raise ProviderError("One of the chosen channels is private or no longer exists. Motif reads public channels only.")
                messages = await self._messages(client, channel_id)
                by_month: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
                for message in messages:
                    if message.get("subtype") in SKIP_SUBTYPES or not message.get("text"):
                        continue
                    by_month[datetime.fromtimestamp(float(message["ts"]), timezone.utc).strftime("%Y-%m")].append(message)
                for month, items in sorted(by_month.items()):
                    items.sort(key=lambda m: float(m["ts"]))
                    lines, day = [], ""
                    for message in items:
                        when = datetime.fromtimestamp(float(message["ts"]), timezone.utc)
                        if when.strftime("%Y-%m-%d") != day:
                            day = when.strftime("%Y-%m-%d")
                            lines += ["", f"## {day}"]
                        who = await self._username(client, users, message["user"]) if message.get("user") else (message.get("username") or "bot")
                        text = clean_message(message["text"], users)
                        reply = message.get("thread_ts") and message.get("thread_ts") != message.get("ts")
                        if text:
                            lines.append(f"{'↳ ' if reply else ''}{who}: {text}")
                    body = "\n".join(lines).strip()[:MAX_TEXT_CHARS]
                    if body:
                        yield RemoteDoc(external_id=f"{channel_id}:{month}", title=f"{names[channel_id]} {month}", kind="meeting", text=f"# {names[channel_id]} {month}\n{body}")
