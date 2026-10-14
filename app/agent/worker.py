"""One-shot durable queue consumer: python -m app.agent.worker."""
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.database import engine
from app.models import User
from app.permissions import get_project_or_404, require_project_owner
from app.agent.models import DebugTask
from app.agent.repositories import binding
from app.agent.workspace import workspace
from app.agent.sandbox import Sandbox, ExecutionTimeout, Cancelled
from app.agent.llm import LLM
from app.agent.debug import debug


def run_one(factory=lambda: Session(engine), llm=None, sandbox=None):
    llm, sandbox = llm or LLM(), sandbox or Sandbox()
    with factory() as db:
        task = db.scalar(select(DebugTask).where(DebugTask.status == "queued").order_by(DebugTask.created_at))
        if task is None:
            return None
        task_id = task.id
        claim = db.execute(update(DebugTask).where(DebugTask.id == task_id,
                                                  DebugTask.status == "queued").values(status="running"))
        db.commit()
        if claim.rowcount != 1:
            return None
        def cancelled():
            with factory() as check:
                return check.get(DebugTask, task_id).status == "cancelled"
        try:
            owner = db.get(User, task.approver_id)
            if owner is None or not owner.is_active:
                raise RuntimeError("Approver no longer active")
            require_project_owner(get_project_or_404(db, task.project_id), owner)
            repo = binding(task.project_id, task.repository)
            sandbox.check()
            with workspace(repo, task.revision) as (path, files):
                report = debug(path, files, task.reason, llm, sandbox, cancelled)
            status = "succeeded" if report["verified"] else "failed"
        except Cancelled:
            status, report = "cancelled", {"error": "Cancelled"}
        except ExecutionTimeout:
            status, report = "timed_out", {"error": "Execution time budget exceeded"}
        except Exception as error:
            status, report = "failed", {"error": type(error).__name__,
                                        "message": "Execution failed; check operator configuration"}
        db.execute(update(DebugTask).where(DebugTask.id == task_id,
            DebugTask.status == "running").values(status=status, report=report))
        db.commit()
        return task_id


if __name__ == "__main__":
    print(run_one() or "No queued task")
