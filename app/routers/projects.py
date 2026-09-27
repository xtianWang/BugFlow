from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Project, ProjectMember, User
from app.permissions import (
    get_project_or_404,
    require_project_access,
    require_project_owner,
)
from app.schemas import (
    MessageResponse,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberResponse,
    ProjectResponse,
    ProjectUpdate,
)


router = APIRouter(
    prefix="/projects",
    tags=["projects"],
)


def project_member_response(
    project: Project,
    membership: ProjectMember,
) -> ProjectMemberResponse:
    return ProjectMemberResponse(
        user_id=membership.user_id,
        username=membership.user.username,
        joined_at=membership.joined_at,
        is_owner=membership.user_id == project.owner_id,
    )


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    project = Project(
        name=data.name,
        description=data.description,
        owner_id=current_user.id,
    )
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=current_user.id))
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Project]:
    statement = (
        select(Project)
        .outerjoin(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            or_(
                Project.owner_id == current_user.id,
                ProjectMember.user_id == current_user.id,
            )
        )
        .distinct()
    )
    return list(db.scalars(statement).all())


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    project = get_project_or_404(db, project_id)
    require_project_access(db, project, current_user)
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Project:
    project = get_project_or_404(db, project_id)
    require_project_owner(project, current_user)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", response_model=MessageResponse)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    project = get_project_or_404(db, project_id)
    require_project_owner(project, current_user)
    db.delete(project)
    db.commit()
    return MessageResponse(message="Project deleted")


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_project_member(
    project_id: int,
    data: ProjectMemberAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectMemberResponse:
    project = get_project_or_404(db, project_id)
    require_project_owner(project, current_user)

    user = db.scalar(select(User).where(User.username == data.username))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is inactive",
        )
    if db.get(ProjectMember, (project.id, user.id)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a project member",
        )

    membership = ProjectMember(project_id=project.id, user_id=user.id)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return project_member_response(project, membership)


@router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
def list_project_members(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProjectMemberResponse]:
    project = get_project_or_404(db, project_id)
    require_project_access(db, project, current_user)
    memberships = db.scalars(
        select(ProjectMember)
        .where(ProjectMember.project_id == project.id)
        .join(ProjectMember.user)
    ).all()
    return [project_member_response(project, membership) for membership in memberships]


@router.delete(
    "/{project_id}/members/{user_id}",
    response_model=MessageResponse,
)
def remove_project_member(
    project_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    project = get_project_or_404(db, project_id)
    require_project_owner(project, current_user)

    if user_id == project.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project owner cannot be removed",
        )

    membership = db.get(ProjectMember, (project.id, user_id))
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project member not found",
        )

    db.delete(membership)
    db.commit()
    return MessageResponse(message="Project member removed")
