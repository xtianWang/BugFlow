from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.permissions import get_project_or_404, require_project_access, require_project_owner
from app.agent.llm import LLM
from app.agent.models import AgentTrace, DebugTask
from app.agent.service import run_chat

router = APIRouter(prefix="/agent", tags=["agent"])


def get_llm():
    return LLM()


class Chat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: int
    message: str = Field(min_length=1, max_length=4000)


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorize_code_execution: Literal[True]
    revision: str


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accepted", "rejected"]


def task_access(db, user, task_id, owner=False):
    task = db.get(DebugTask, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    project = get_project_or_404(db, task.project_id)
    require_project_access(db, project, user)
    if owner:
        require_project_owner(project, user)
    return task


@router.post("/chat")
def chat(data: Chat, db: Session = Depends(get_db),
         user: User = Depends(get_current_user), llm=Depends(get_llm)):
    return run_chat(db, user, data.project_id, data.message, llm)


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = task_access(db, user, task_id)
    return {k: getattr(task, k) for k in ("id", "project_id", "repository", "revision", "reason",
                                          "status", "decision", "report", "approver_id")}


@router.post("/tasks/{task_id}/approve")
def approve(task_id: str, data: Approval, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    task = task_access(db, user, task_id, owner=True)
    if data.revision != task.revision:
        raise HTTPException(409, "Review the exact task revision before approval")
    changed = db.execute(update(DebugTask).where(DebugTask.id == task.id,
        DebugTask.status == "awaiting_authorization").values(status="queued", approver_id=user.id))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Task already decided")
    db.commit()
    return {"status": "queued"}


@router.post("/tasks/{task_id}/cancel")
def cancel(task_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = task_access(db, user, task_id, owner=True)
    changed = db.execute(update(DebugTask).where(DebugTask.id == task.id,
        DebugTask.status.in_(["awaiting_authorization", "queued", "running"])).values(status="cancelled"))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Task is terminal")
    db.commit()
    return {"status": "cancelled"}


@router.post("/tasks/{task_id}/review")
def review(task_id: str, data: Review, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = task_access(db, user, task_id, owner=True)
    if task.status != "succeeded" or task.decision is not None:
        raise HTTPException(409, "Only an unreviewed successful report can be reviewed")
    changed = db.execute(update(DebugTask).where(DebugTask.id == task.id,
        DebugTask.status == "succeeded", DebugTask.decision.is_(None)).values(decision=data.decision))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Report already reviewed")
    db.commit()
    return {"decision": data.decision, "applied_to_original": False}


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trace = db.get(AgentTrace, trace_id)
    if trace is None:
        raise HTTPException(404, "Trace not found")
    require_project_access(db, get_project_or_404(db, trace.project_id), user)
    return {"id": trace.id, "status": trace.status, "events": trace.events}
