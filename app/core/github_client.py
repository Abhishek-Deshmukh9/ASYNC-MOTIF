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
    """
    Dispatches a structured issue to GitHub REST API v3 (POST /repos/{owner}/{repo}/issues).
    If GITHUB_TOKEN is configured, sends to real GitHub API.
    Otherwise (or if the API call fails) no issue is created: the receipt says so
    plainly and carries no URL, so the UI never shows a link to an issue that doesn't exist.
    """
    repo_owner = owner or settings.GITHUB_REPO_OWNER
    repo_name = repo or settings.GITHUB_REPO_NAME
    token = settings.GITHUB_TOKEN
    issue_labels = labels or ["motif-approved", "theme", "revenue-risk:critical"]

    if token and not (repo_owner and repo_name):
        logger.warning("GITHUB_TOKEN is set but GITHUB_REPO_OWNER / GITHUB_REPO_NAME are not; no issue created.")
        return {
            "issue_number": None,
            "issue_url": None,
            "is_live": False,
            "message": "No GitHub issue was created: set GITHUB_REPO_OWNER and GITHUB_REPO_NAME in .env.",
        }

    if token:
        url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/issues"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "Motif-Autonomous-Pipeline/1.0",
        }
        payload = {
            "title": title,
            "body": body,
            "labels": issue_labels,
        }

        try:
            logger.info(f"Dispatching issue to GitHub repository: {repo_owner}/{repo_name}...")
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                logger.info(f"GitHub issue created: {data.get('html_url')} (#{data.get('number')})")
                return {
                    "issue_number": data.get("number"),
                    "issue_url": data.get("html_url"),
                    "is_live": True,
                }
        except Exception as e:
            logger.warning(f"GitHub API call failed ({e}); no issue was created.")
            return {
                "issue_number": None,
                "issue_url": None,
                "is_live": False,
                "message": f"GitHub API call failed, so no issue was created: {e}",
            }

    # No token configured: the PRD is still generated, but nothing is sent to GitHub.
    logger.info("GITHUB_TOKEN not set; skipping GitHub issue creation (simulated mode).")
    return {
        "issue_number": None,
        "issue_url": None,
        "is_live": False,
        "message": "Simulated mode: PRD generated, but no GitHub issue was created because GITHUB_TOKEN is not set.",
    }
