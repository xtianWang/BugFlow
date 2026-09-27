from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Issue, User
from app.permissions import (
    get_issue_or_404,
    get_project_or_404,
    require_issue_access,
    require_issue_delete_permission,
    require_project_access,
    validate_issue_assignee,
)
from app.schemas import (
    IssueCreate,
    IssueResponse,
    IssueStatusUpdate,
    IssueUpdate,
    MessageResponse,
)


router = APIRouter(
    prefix="",
    tags=["issues"],
)


STATUS_TRANSITIONS = {
    "open": "in_progress",
    "in_progress": "resolved",
    "resolved": "closed",
}


@router.post(
    "/projects/{project_id}/issues",
    response_model=IssueResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_issue(
    project_id: int,
    data: IssueCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    project = get_project_or_404(db, project_id)
    require_project_access(db, project, current_user)
    validate_issue_assignee(db, project, data.assignee_id)

    issue = Issue(
        title=data.title,
        description=data.description,
        priority=data.priority,
        project_id=project.id,
        creator_id=current_user.id,
        assignee_id=data.assignee_id,
    )
    db.add(issue)
    db.commit()
    db.refresh(issue)
    return issue


@router.get("/projects/{project_id}/issues", response_model=list[IssueResponse])
def list_project_issues(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Issue]:
    project = get_project_or_404(db, project_id)
    require_project_access(db, project, current_user)
    statement = (
        select(Issue)
        .where(Issue.project_id == project.id)
        .order_by(Issue.id.asc())
    )
    return list(db.scalars(statement).all())


@router.get("/issues/{issue_id}", response_model=IssueResponse)
def get_issue(
    issue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    issue = get_issue_or_404(db, issue_id)
    require_issue_access(db, issue, current_user)
    return issue


@router.patch("/issues/{issue_id}", response_model=IssueResponse)
def update_issue(
    issue_id: int,
    data: IssueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    issue = get_issue_or_404(db, issue_id)
    require_issue_access(db, issue, current_user)

    update_data = data.model_dump(exclude_unset=True)
    if "assignee_id" in update_data:
        validate_issue_assignee(db, issue.project, update_data["assignee_id"])

    for field, value in update_data.items():
        setattr(issue, field, value)

    db.commit()
    db.refresh(issue)
    return issue


@router.patch("/issues/{issue_id}/status", response_model=IssueResponse)
def update_issue_status(
    issue_id: int,
    data: IssueStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Issue:
    issue = get_issue_or_404(db, issue_id)
    require_issue_access(db, issue, current_user)

    if data.status != STATUS_TRANSITIONS.get(issue.status):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid issue status transition",
        )

    issue.status = data.status
    db.commit()
    db.refresh(issue)
    return issue


@router.delete("/issues/{issue_id}", response_model=MessageResponse)
def delete_issue(
    issue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    issue = get_issue_or_404(db, issue_id)
    require_issue_delete_permission(issue, current_user)
    db.delete(issue)
    db.commit()
    return MessageResponse(message="Issue deleted")
