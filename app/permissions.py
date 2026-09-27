from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Issue, Project, ProjectMember, User


def get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


def is_project_member(db: Session, project_id: int, user_id: int) -> bool:
    return db.get(ProjectMember, (project_id, user_id)) is not None


def require_project_access(db: Session, project: Project, user: User) -> None:
    if project.owner_id == user.id or is_project_member(db, project.id, user.id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to access this project",
    )


def require_project_owner(project: Project, user: User) -> None:
    if project.owner_id == user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Project owner permission required",
    )


def get_issue_or_404(db: Session, issue_id: int) -> Issue:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    return issue


def require_issue_access(db: Session, issue: Issue, user: User) -> None:
    require_project_access(db, issue.project, user)


def require_issue_delete_permission(issue: Issue, user: User) -> None:
    require_project_owner(issue.project, user)


def validate_issue_assignee(
    db: Session,
    project: Project,
    assignee_id: int | None,
) -> None:
    if assignee_id is None:
        return

    assignee = db.get(User, assignee_id)
    if assignee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assignee not found",
        )
    if not assignee.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assignee is inactive",
        )
    if not is_project_member(db, project.id, assignee_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assignee must be a project member",
        )
