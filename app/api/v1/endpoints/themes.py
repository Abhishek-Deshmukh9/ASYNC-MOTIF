import logging
import uuid
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import copy

from pydantic import BaseModel
from sqlalchemy import Integer, desc, func, select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.core.auth import CurrentUser, get_current_user
from app.core.scoring import ISSUE_TYPES, retype_breakdowns
from app.core.issue_target import DEMO_READ_ONLY_MESSAGE, demo_is_locked, resolve_issue_target
from app.core.projects import authorize_project, project_uuid
from app.models.project import Project
from app.models.theme import Theme
from app.models.feedback import FeedbackItem, theme_feedback_associations
from app.models.audit import ApprovalAuditLog
from app.schemas.theme import ThemeResponse, ThemeUpdate, ThemeApprovalRequest, CitedQuote
from app.core.prd_generator import generate_mini_prd
from app.core.github_client import dispatch_github_issue
from app.config import settings

logger = logging.getLogger(__name__)

DECIDED = ("approved", "rejected")


async def _activity(db: AsyncSession, theme_ids: List[UUID]) -> Dict[UUID, List[Dict[str, Any]]]:
    """Who did what to each theme, newest first, from the audit log."""
    if not theme_ids:
        return {}
    rows = (await db.execute(
        select(ApprovalAuditLog.theme_id, ApprovalAuditLog.action, ApprovalAuditLog.pm_user_id, ApprovalAuditLog.timestamp, ApprovalAuditLog.original_title, ApprovalAuditLog.final_title)
        .where(ApprovalAuditLog.theme_id.in_(theme_ids))
        .order_by(desc(ApprovalAuditLog.timestamp))
    )).all()
    out: Dict[UUID, List[Dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row.theme_id, []).append({
            "action": row.action, "by": row.pm_user_id,
            "at": row.timestamp.isoformat() if row.timestamp else None, "title": row.final_title,
            "changed_title": bool(row.original_title and row.final_title and row.original_title != row.final_title),
        })
    return out


async def _lock_undecided(db: AsyncSession, theme_id: UUID) -> Theme:
    """
    Lock the theme row for the rest of this request, so two teammates acting at once are handled one at a
    time. If someone already approved or rejected it, stop and say who, instead of acting twice.
    """
    theme = await db.scalar(select(Theme).where(Theme.id == theme_id).with_for_update().execution_options(populate_existing=True))
    if theme is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Theme {theme_id} not found")
    if theme.status in DECIDED:
        by = await db.scalar(
            select(ApprovalAuditLog.pm_user_id)
            .where(ApprovalAuditLog.theme_id == theme.id, ApprovalAuditLog.action == theme.status)
            .order_by(desc(ApprovalAuditLog.timestamp)).limit(1)
        )
        decided = theme.status
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Already {decided} by {by or 'a teammate'}. Refresh to see the latest.")
    return theme


router = APIRouter(prefix="/themes", tags=["Themes"])


@router.get("", response_model=List[ThemeResponse])
async def list_themes(
    status_filter: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """
    Lists discovered themes ordered by Revenue-at-Risk descending (Rule 1.4). Themes from
    documents and notes carry no ARR, so ties are broken by how many passages mention them.
    """
    await authorize_project(db, project_id, user)
    mentions = (
        select(func.count())
        .select_from(theme_feedback_associations)
        .where(theme_feedback_associations.c.theme_id == Theme.id)
        .correlate(Theme)
        .scalar_subquery()
    )
    query = (
        select(Theme)
        .order_by(Theme.score_breakdown['rank'].astext.cast(Integer).asc().nulls_last(), Theme.priority_score.desc().nulls_last(), desc(Theme.revenue_at_risk), desc(mentions), desc(Theme.created_at))
        .offset(offset)
        .limit(limit)
    )
    if status_filter:
        query = query.where(Theme.status == status_filter)
    query = query.where(Theme.project_id == project_id if project_id is not None else Theme.project_id.is_(None))

    result = await db.execute(query)
    themes = result.scalars().all()

    response: List[ThemeResponse] = []
    if not themes:
        return response

    theme_ids = [t.id for t in themes]
    activity = await _activity(db, theme_ids)
    assoc_query = (
        select(
            theme_feedback_associations.c.theme_id,
            theme_feedback_associations.c.quote_text,
            theme_feedback_associations.c.feedback_item_id,
            FeedbackItem.customer_id,
            FeedbackItem.arr_value,
            FeedbackItem.customer_tier,
            FeedbackItem.metadata_["source_name"].astext.label("source_name"),
        )
        .join(
            FeedbackItem,
            theme_feedback_associations.c.feedback_item_id == FeedbackItem.id,
        )
        .where(
            theme_feedback_associations.c.theme_id.in_(theme_ids),
            theme_feedback_associations.c.is_cited_quote.is_(True),
        )
    )
    assoc_res = await db.execute(assoc_query)
    assoc_rows = assoc_res.all()

    # Evidence counts: passages in each theme, and how many distinct sources they come from
    count_rows = (
        await db.execute(
            select(
                theme_feedback_associations.c.theme_id,
                func.count().label("mentions"),
                func.count(func.distinct(FeedbackItem.source_id)).label("sources"),
            )
            .join(FeedbackItem, theme_feedback_associations.c.feedback_item_id == FeedbackItem.id)
            .where(theme_feedback_associations.c.theme_id.in_(theme_ids))
            .group_by(theme_feedback_associations.c.theme_id)
        )
    ).all()
    counts = {row.theme_id: (row.mentions, row.sources) for row in count_rows}

    quotes_by_theme: Dict[UUID, List[CitedQuote]] = {t.id: [] for t in themes}
    for row in assoc_rows:
        if row.quote_text:
            quotes_by_theme[row.theme_id].append(
                CitedQuote(
                    quote_text=row.quote_text,
                    feedback_item_id=row.feedback_item_id,
                    customer_id=row.customer_id,
                    arr_value=float(row.arr_value or 0.0),
                    customer_tier=row.customer_tier,
                    source_name=row.source_name,
                )
            )

    for t in themes:
        quotes = quotes_by_theme.get(t.id, [])
        response.append(
            ThemeResponse(
                id=t.id,
                cluster_id=t.cluster_id,
                title=t.title,
                summary=t.summary,
                revenue_at_risk=float(t.revenue_at_risk or 0.0),
                affected_accounts_count=t.affected_accounts_count or 0,
                status=t.status,
                prd_markdown=t.prd_markdown,
                priority_score=float(t.priority_score) if t.priority_score is not None else None,
                score_breakdown=t.score_breakdown,
                activity=activity.get(t.id, []),
                github_issue_url=t.github_issue_url,
                github_issue_number=t.github_issue_number,
                created_at=t.created_at,
                updated_at=t.updated_at,
                cited_quotes=quotes,
                mention_count=counts.get(t.id, (0, 0))[0],
                source_count=counts.get(t.id, (0, 0))[1],
            )
        )

    return response


@router.get("/{theme_id}", response_model=ThemeResponse)
async def get_theme(
    theme_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """Fetch details, Mini-PRD, and verified quotes for a specific theme."""
    query = select(Theme).where(Theme.id == theme_id)
    result = await db.execute(query)
    theme = result.scalar_one_or_none()

    if not theme:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Theme with id {theme_id} not found.",
        )
    await authorize_project(db, theme.project_id, user)

    assoc_query = (
        select(
            theme_feedback_associations.c.quote_text,
            theme_feedback_associations.c.feedback_item_id,
            FeedbackItem.customer_id,
            FeedbackItem.arr_value,
            FeedbackItem.customer_tier,
            FeedbackItem.metadata_["source_name"].astext.label("source_name"),
        )
        .join(
            FeedbackItem,
            theme_feedback_associations.c.feedback_item_id == FeedbackItem.id,
        )
        .where(
            theme_feedback_associations.c.theme_id == theme.id,
            theme_feedback_associations.c.is_cited_quote.is_(True),
        )
    )
    assoc_res = await db.execute(assoc_query)
    assoc_rows = assoc_res.all()

    quotes = [
        CitedQuote(
            quote_text=row.quote_text or "",
            feedback_item_id=row.feedback_item_id,
            customer_id=row.customer_id,
            arr_value=float(row.arr_value or 0.0),
            customer_tier=row.customer_tier,
            source_name=row.source_name,
        )
        for row in assoc_rows
        if row.quote_text
    ]

    return ThemeResponse(
        id=theme.id,
        cluster_id=theme.cluster_id,
        title=theme.title,
        summary=theme.summary,
        revenue_at_risk=float(theme.revenue_at_risk or 0.0),
        affected_accounts_count=theme.affected_accounts_count or 0,
        status=theme.status,
        prd_markdown=theme.prd_markdown,
        priority_score=float(theme.priority_score) if theme.priority_score is not None else None,
        score_breakdown=theme.score_breakdown,
        activity=(await _activity(db, [theme.id])).get(theme.id, []),
        github_issue_url=theme.github_issue_url,
        github_issue_number=theme.github_issue_number,
        created_at=theme.created_at,
        updated_at=theme.updated_at,
        cited_quotes=quotes,
    )


@router.patch("/{theme_id}", response_model=ThemeResponse)
async def update_theme(
    theme_id: UUID,
    payload: ThemeUpdate,
    pm_user_id: str = "pm_user_default",
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """Allows PM to edit theme title, summary, or priority adjustments."""
    query = select(Theme).where(Theme.id == theme_id)
    result = await db.execute(query)
    theme = result.scalar_one_or_none()

    if not theme:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Theme {theme_id} not found",
        )
    await authorize_project(db, theme.project_id, user, need="edit")
    if demo_is_locked(project_id=theme.project_id, signed_in=user is not None, writable=settings.DEMO_WRITABLE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEMO_READ_ONLY_MESSAGE)
    if payload.status is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use Approve or Reject to change a theme's status.")
    theme = await _lock_undecided(db, theme_id)

    if user is not None:
        pm_user_id = user.email or user.id
    original_title = theme.title
    if payload.title is not None:
        theme.title = payload.title
    if payload.summary is not None:
        theme.summary = payload.summary
    if payload.revenue_at_risk is not None:
        theme.revenue_at_risk = payload.revenue_at_risk
    if payload.status is not None:
        theme.status = payload.status

    # Record in audit log
    audit_log = ApprovalAuditLog(
        id=uuid.uuid4(),
        theme_id=theme.id,
        pm_user_id=pm_user_id,
        action="edited",
        original_title=original_title,
        final_title=theme.title,
    )
    db.add(audit_log)
    await db.commit()
    await db.refresh(theme)

    return await get_theme(theme_id, db, user)


@router.post("/{theme_id}/approve", response_model=Dict[str, Any])
async def approve_and_dispatch_theme(
    theme_id: UUID,
    request: Optional[ThemeApprovalRequest] = None,
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """
    Human-in-the-Loop Approval Gate (Rule 1.3):
    1. Validates PM approval signature.
    2. Auto-compiles standardized mini-PRD with Gherkin acceptance criteria (FR-6.1).
    3. Dispatches structured issue to GitHub REST API with labels (FR-6.2).
    4. Updates theme status to 'approved' and records action in ApprovalAuditLog.
    """
    pm_id = request.pm_user_id if request else "pm_lead"
    if user is not None:
        pm_id = user.email or user.id
    query = select(Theme).where(Theme.id == theme_id)
    result = await db.execute(query)
    theme = result.scalar_one_or_none()

    if not theme:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Theme {theme_id} not found",
        )
    await authorize_project(db, theme.project_id, user, need="edit")
    theme = await _lock_undecided(db, theme_id)

    # A project's issues go to its own saved repository, else the backend's configured one.
    # The shared demo never opens real issues for signed-in users, and a request cannot steer
    # the server's GitHub token to another repo (see resolve_issue_target).
    project_repo = None
    if theme.project_id is not None:
        project_repo = await db.scalar(select(Project.github_repo).where(Project.id == project_uuid(theme.project_id)))
    target = resolve_issue_target(
        shared_demo=theme.project_id is None,
        signed_in=user is not None,
        project_repo=project_repo,
        requested_repo=request.github_repo if request else None,
        default_owner=settings.GITHUB_REPO_OWNER,
        default_repo=settings.GITHUB_REPO_NAME,
        demo_may_create_issues=settings.DEMO_WRITABLE,
    )
    repo_owner, repo_name = target.owner, target.repo

    original_title = theme.title
    if request and request.final_title:
        theme.title = request.final_title
    if request and request.final_summary and request.final_summary != theme.summary:
        theme.summary = request.final_summary
        # A summary edit is still an edit: record it so the acceptance rate doesn't count it as "as-is"
        db.add(
            ApprovalAuditLog(
                id=uuid.uuid4(),
                theme_id=theme.id,
                pm_user_id=pm_id,
                action="edited",
                original_title=original_title,
                final_title=theme.title,
            )
        )

    # Fetch quotes for this theme
    assoc_query = (
        select(
            theme_feedback_associations.c.quote_text,
            FeedbackItem.customer_id,
            FeedbackItem.arr_value,
            FeedbackItem.customer_tier,
            FeedbackItem.metadata_["source_name"].astext.label("source_name"),
        )
        .join(
            FeedbackItem,
            theme_feedback_associations.c.feedback_item_id == FeedbackItem.id,
        )
        .where(
            theme_feedback_associations.c.theme_id == theme.id,
            theme_feedback_associations.c.is_cited_quote.is_(True),
        )
    )
    assoc_res = await db.execute(assoc_query)
    assoc_rows = assoc_res.all()

    quote_dicts = [
        {
            "quote_text": r.quote_text,
            "customer_id": r.customer_id,
            "arr_value": float(r.arr_value or 0.0),
            "customer_tier": r.customer_tier,
            "source_name": r.source_name,
        }
        for r in assoc_rows
        if r.quote_text
    ]

    # 1. Compile standardized mini-PRD (FR-6.1)
    prd_markdown = generate_mini_prd(
        theme_title=theme.title,
        problem_summary=theme.summary,
        revenue_at_risk=float(theme.revenue_at_risk or 0.0),
        affected_accounts_count=theme.affected_accounts_count or 0,
        cited_quotes=quote_dicts,
        cluster_id=theme.cluster_id,
    )
    theme.prd_markdown = prd_markdown

    # 2. Dispatch to GitHub REST API (FR-6.2)
    if not target.allowed:
        # Shared demo: hand back the PRD as a preview and save nothing (no status, edits or audit rows).
        preview = {
            "status": "approved",
            "theme_id": str(theme.id),
            "title": theme.title,
            "revenue_at_risk": float(theme.revenue_at_risk or 0.0),
            "github_issue_url": None,
            "github_issue_number": None,
            "github_dispatch": "simulated",
            "github_message": target.message,
            "prd_markdown": prd_markdown,
            "audit_logged": False,
        }
        await db.rollback()
        return preview

    gh_receipt = await dispatch_github_issue(
        title=f"[MOTIF-THEME] {theme.title}",
        body=prd_markdown,
        labels=["motif-approved", "theme", "revenue-risk:critical"],
        owner=repo_owner,
        repo=repo_name,
    )

    theme.status = "approved"
    theme.github_issue_url = gh_receipt.get("issue_url")
    theme.github_issue_number = gh_receipt.get("issue_number")

    # 3. Log audit event
    audit_log = ApprovalAuditLog(
        id=uuid.uuid4(),
        theme_id=theme.id,
        pm_user_id=pm_id,
        action="approved",
        original_title=original_title,
        final_title=theme.title,
    )
    db.add(audit_log)
    await db.commit()
    await db.refresh(theme)

    if theme.github_issue_url:
        logger.info(f"Theme {theme.id} approved by PM '{pm_id}' -> GitHub issue created: {theme.github_issue_url}")
    else:
        logger.info(f"Theme {theme.id} approved by PM '{pm_id}' -> no GitHub issue ({gh_receipt.get('message')})")

    return {
        "status": "approved",
        "theme_id": str(theme.id),
        "title": theme.title,
        "revenue_at_risk": float(theme.revenue_at_risk),
        "github_issue_url": theme.github_issue_url,
        "github_issue_number": theme.github_issue_number,
        "github_dispatch": "live" if gh_receipt.get("is_live") else "simulated",
        "github_message": gh_receipt.get("message"),
        "prd_markdown": theme.prd_markdown,
        "audit_logged": True,
    }


@router.post("/{theme_id}/reject", response_model=Dict[str, Any])
async def reject_theme(
    theme_id: UUID,
    pm_user_id: str = "pm_lead",
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """Marks theme as rejected and records in audit log."""
    query = select(Theme).where(Theme.id == theme_id)
    result = await db.execute(query)
    theme = result.scalar_one_or_none()

    if not theme:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Theme {theme_id} not found",
        )
    await authorize_project(db, theme.project_id, user, need="edit")
    if demo_is_locked(project_id=theme.project_id, signed_in=user is not None, writable=settings.DEMO_WRITABLE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEMO_READ_ONLY_MESSAGE)

    theme = await _lock_undecided(db, theme_id)
    if user is not None:
        pm_user_id = user.email or user.id
    theme.status = "rejected"
    audit_log = ApprovalAuditLog(
        id=uuid.uuid4(),
        theme_id=theme.id,
        pm_user_id=pm_user_id,
        action="rejected",
        original_title=theme.title,
        final_title=theme.title,
    )
    db.add(audit_log)
    await db.commit()

    return {
        "status": "rejected",
        "theme_id": str(theme.id),
        "message": "Theme rejected and archived from active queue.",
    }


class IssueTypeChange(BaseModel):
    issue_type: str


@router.patch("/{theme_id}/type", response_model=Dict[str, Any])
async def change_issue_type(
    theme_id: UUID,
    body: IssueTypeChange,
    db: AsyncSession = Depends(get_db),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """
    A PM says what kind of problem a theme really is. Its weights change to that type's (base x multiplier,
    rescaled) and every theme in the project is re-ranked; Security goes to Fix first. Recorded in the history.
    """
    if body.issue_type not in ISSUE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Type must be one of: {', '.join(ISSUE_TYPES)}.")
    theme = await db.scalar(select(Theme).where(Theme.id == theme_id))
    if theme is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Theme {theme_id} not found")
    await authorize_project(db, theme.project_id, user, need="edit")
    if demo_is_locked(project_id=theme.project_id, signed_in=user is not None, writable=settings.DEMO_WRITABLE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=DEMO_READ_ONLY_MESSAGE)
    theme = await _lock_undecided(db, theme_id)
    if not theme.score_breakdown or not theme.score_breakdown.get("signals"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This theme has no score yet. Analyze the project again first.")

    # Every scored theme in the same project, locked, so two people re-typing at once are handled in turn
    same_scope = Theme.project_id == theme.project_id if theme.project_id is not None else Theme.project_id.is_(None)
    peers = (await db.scalars(
        select(Theme).where(same_scope, Theme.score_breakdown.isnot(None)).order_by(Theme.id).with_for_update()
    )).all()
    breakdowns = [copy.deepcopy(peer.score_breakdown) for peer in peers]
    index = next(i for i, peer in enumerate(peers) if peer.id == theme.id)
    previous = (breakdowns[index].get("issue_type") or {}).get("label", "General")
    retype_breakdowns(breakdowns, index, body.issue_type)
    for peer, breakdown in zip(peers, breakdowns):
        peer.score_breakdown = breakdown
        peer.priority_score = breakdown["priority_score"]
        flag_modified(peer, "score_breakdown")

    db.add(ApprovalAuditLog(
        id=uuid.uuid4(), theme_id=theme.id, pm_user_id=(user.email or user.id) if user else "pm_lead",
        action="type_changed", original_title=previous, final_title=ISSUE_TYPES[body.issue_type]["label"],
    ))
    await db.commit()
    updated = breakdowns[index]
    return {
        "theme_id": str(theme.id),
        "issue_type": updated["issue_type"],
        "rank": updated["rank"],
        "of": updated["of"],
        "priority_score": updated["priority_score"],
    }
