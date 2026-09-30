"""
GitHub Issues: import a repository's issues and their comments as feedback.
Public repositories work without a token (with a low rate limit); private ones need a token that can read issues.
"""
import re
from typing import Any, AsyncIterator, Dict, List

from app.integrations.base import MAX_DOCS_PER_SYNC, MAX_TEXT_CHARS, Provider, ProviderError, RemoteDoc, send

API = "https://api.github.com"
REPO = re.compile(r"^(?:https?://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
MAX_COMMENT_ISSUES_ANONYMOUS = 30   # unauthenticated GitHub allows only 60 requests an hour
MAX_COMMENTS_PER_ISSUE = 50


def parse_repo(value: str) -> str:
    match = REPO.match((value or "").strip())
    if not match:
        raise ProviderError("Write the repository as owner/repo, for example acme/product.")
    return f"{match.group(1)}/{match.group(2)}"


class GitHubIssuesProvider(Provider):
    name = "github"
    label = "GitHub Issues"

    def _repo(self) -> str:
        return parse_repo(self.credentials.get("repo", ""))

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Motif"}
        token = (self.credentials.get("token") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _get(self, client, path: str, **params) -> Any:
        response = await send(client, "GET", f"{API}{path}", service="GitHub", headers=self._headers(), params=params)
        if response.status_code == 401:
            raise ProviderError("GitHub rejected this token. Create a new one, or leave it empty for a public repository.")
        if response.status_code == 404:
            raise ProviderError("GitHub cannot find that repository. Check the name, or add a token that can read it if it is private.")
        if response.status_code == 403:
            if response.headers.get("X-RateLimit-Remaining") == "0":
                raise ProviderError("GitHub's rate limit was reached. Add a token to raise it, or try again in an hour.")
            raise ProviderError("GitHub refused access. The token needs permission to read this repository's issues.")
        if response.status_code >= 400:
            raise ProviderError(f"GitHub returned an error ({response.status_code}).")
        return response.json()

    async def validate(self) -> Dict[str, Any]:
        repo = self._repo()
        async with self.client() as client:
            data = await self._get(client, f"/repos/{repo}")
        if data.get("has_issues") is False:
            raise ProviderError("Issues are turned off for this repository.")
        return {"display_name": data.get("full_name") or repo}

    async def options(self) -> List[Dict[str, Any]]:
        return []

    async def documents(self, config: Dict[str, Any]) -> AsyncIterator[RemoteDoc]:
        repo = self._repo()
        state = "all" if config.get("state", "all") == "all" else "open"
        with_comments = config.get("include_comments", True)
        has_token = bool((self.credentials.get("token") or "").strip())
        commented = 0
        count = 0
        async with self.client() as client:
            page = 1
            while count < MAX_DOCS_PER_SYNC:
                issues = await self._get(client, f"/repos/{repo}/issues", state=state, sort="updated", direction="desc", per_page=100, page=page)
                if not issues:
                    return
                for issue in issues:
                    if "pull_request" in issue:
                        continue  # pull requests are not customer feedback
                    lines = [f"# {issue['title']}", "", f"Opened by {(issue.get('user') or {}).get('login', 'someone')} · {issue.get('state', 'open')}"]
                    labels = [label["name"] for label in issue.get("labels", []) if isinstance(label, dict)]
                    if labels:
                        lines.append(f"Labels: {', '.join(labels)}")
                    votes = (issue.get("reactions") or {}).get("+1", 0)
                    if votes:
                        lines.append(f"{votes} people gave this a thumbs up")
                    if (issue.get("body") or "").strip():
                        lines += ["", issue["body"].strip()]
                    if with_comments and issue.get("comments") and (has_token or commented < MAX_COMMENT_ISSUES_ANONYMOUS):
                        commented += 1
                        comments = await self._get(client, f"/repos/{repo}/issues/{issue['number']}/comments", per_page=MAX_COMMENTS_PER_ISSUE)
                        replies = [f"{(c.get('user') or {}).get('login', 'someone')}: {' '.join((c.get('body') or '').split())}" for c in comments if (c.get("body") or "").strip()]
                        if replies:
                            lines += ["", "## Comments"] + replies
                    yield RemoteDoc(external_id=f"issue-{issue['number']}", title=f"#{issue['number']} {issue['title']}", url=issue.get("html_url"), kind="document", text="\n".join(lines)[:MAX_TEXT_CHARS])
                    count += 1
                    if count >= MAX_DOCS_PER_SYNC:
                        return
                if len(issues) < 100:
                    return
                page += 1
