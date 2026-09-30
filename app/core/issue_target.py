"""Decide where (and whether) approving a theme may open a real GitHub issue."""
from dataclasses import dataclass
from typing import Optional

DEMO_BLOCKED_MESSAGE = (
    "The shared demo never opens real GitHub issues. The PRD was generated; "
    "create your own project to send an issue to your repository."
)


@dataclass(frozen=True)
class IssueTarget:
    owner: Optional[str]
    repo: Optional[str]
    allowed: bool = True
    message: Optional[str] = None


def resolve_issue_target(
    *,
    shared_demo: bool,
    signed_in: bool,
    project_repo: Optional[str],
    requested_repo: Optional[str],
    default_owner: Optional[str],
    default_repo: Optional[str],
    demo_may_create_issues: bool = False,
) -> IssueTarget:
    """
    Signed-in users share one server GitHub token, so they must not be able to steer it:
    - the shared demo corpus belongs to nobody, so it never opens real issues (unless the operator opts in);
    - a project's issues go to that project's saved repository, never to a repo named in the request.
    With sign-in off (local development) the old behaviour is kept.
    """
    if signed_in and shared_demo and not demo_may_create_issues:
        return IssueTarget(None, None, allowed=False, message=DEMO_BLOCKED_MESSAGE)

    if signed_in:
        chosen = None if shared_demo else project_repo
    else:
        chosen = requested_repo or project_repo

    if chosen and "/" in chosen:
        owner, repo = chosen.split("/", 1)
        return IssueTarget(owner, repo)
    return IssueTarget(default_owner, default_repo)
