from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Project, ProjectMember, User


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
