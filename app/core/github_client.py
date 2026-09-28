import logging
from typing import Any, Dict, List, Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


async def dispatch_github_issue(
    title: str,
    body: str,
    labels: Optional[List[str]] = None,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a real issue via GitHub REST API; never fabricate an issue receipt."""
    repo_owner = owner or settings.GITHUB_REPO_OWNER
    repo_name = repo or settings.GITHUB_REPO_NAME
    token = settings.GITHUB_TOKEN
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not configured; no GitHub issue was created.")
    if not repo_owner or not repo_name:
        raise RuntimeError("No GitHub repository was configured for this project.")

    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "Motif-Feedback-Intelligence/1.0",
    }
    payload = {
        "title": title,
        "body": body,
        "labels": labels or ["motif-approved", "theme", "revenue-risk:critical"],
    }
    try:
        logger.info("Dispatching issue to GitHub repository %s/%s", repo_owner, repo_name)
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.exception("GitHub issue creation failed for %s/%s", repo_owner, repo_name)
        raise RuntimeError(f"GitHub issue creation failed: {exc}") from exc

    logger.info("Created GitHub issue %s (number %s)", data.get("html_url"), data.get("number"))
    return {
        "issue_number": data.get("number"),
        "issue_url": data.get("html_url"),
        "is_live": True,
    }
