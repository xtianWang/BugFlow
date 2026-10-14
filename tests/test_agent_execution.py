import json
from pathlib import Path
import subprocess
import pytest
from app.agent.workspace import workspace, diff, safe_name
from app.agent.sandbox import Sandbox, SandboxUnavailable, ExecutionTimeout
from app.agent.debug import debug
from app.agent.models import DebugTask
from app.agent.worker import run_one
from test_agent import ScriptedLLM, call
from conftest import test_engine
from sqlalchemy.orm import Session
from app.models import User, Project


def test_model_proposal_requires_separate_owner_approval(client, db_session, repository, monkeypatch):
    from app.main import app
    from app.routers.agent import get_llm
    repo, sha = repository
    user = client.post('/auth/register', json={'username': 'proposal_owner', 'password': 'securepass123'}).json()
    token = client.post('/auth/login', json={'username': 'proposal_owner', 'password': 'securepass123'}).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    project = client.post('/projects', json={'name': 'proposal'}, headers=headers).json()
    monkeypatch.setenv('BUGFLOW_AGENT_REPOSITORIES', json.dumps({'demo': {'project_id': project['id'], 'path': str(repo)}}))
    model = ScriptedLLM([call('request_debug', repository='demo', reason='investigate'), {'content': 'approval required'}])
    app.dependency_overrides[get_llm] = lambda: model
    try:
        response = client.post('/agent/chat', json={'project_id': project['id'], 'message': 'debug demo'}, headers=headers)
        assert response.status_code == 200
        task_id = response.json()['debug_task_ids'][0]
        task = db_session.get(DebugTask, task_id)
        assert task.status == 'awaiting_authorization'
        assert task.approver_id is None and task.revision == sha
        assert run_one(lambda: Session(test_engine)) is None
        assert client.post(f'/agent/tasks/{task_id}/approve', headers=headers,
                           json={'authorize_code_execution': True, 'revision': sha}).status_code == 200
        monkeypatch.setattr('app.agent.sandbox.sys.platform', 'win32')
        run_one(lambda: Session(test_engine))
        db_session.refresh(task)
        assert task.status == 'failed'
        assert task.report['error'] == 'SandboxUnavailable'
    finally:
        app.dependency_overrides.pop(get_llm, None)


@pytest.fixture
def repository(tmp_path):
    def git(*args):
        result = subprocess.run(["git", "-C", str(tmp_path), *args], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    git("init")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    git("add", ".")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
    return tmp_path, git("rev-parse", "HEAD")


class EvidenceStub:
    """Inject process results to test orchestration; NOT evidence of a real sandbox run."""
    def __init__(self, codes):
        self.codes = iter(codes)
    def check(self):
        pass
    def run(self, path, files, cancelled):
        return {"exit_code": next(self.codes), "output": "test double"}


def test_real_worktree_patch_and_cleanup(repository):
    repo, sha = repository
    original = (repo / "app/calc.py").read_bytes()
    with workspace(repo, sha) as (path, files):
        llm = ScriptedLLM([call("replace_file", path="app/calc.py", content="def add(a, b):\n    return a + b\n"),
                           call("run_tests"), {"content": "changed operator"}])
        report = debug(path, files, "addition bug", llm, EvidenceStub([1, 0]), lambda: False)
        assert report["verified"]
        assert "+    return a + b" in report["diff"]
        isolated = path
    assert not isolated.exists()
    assert (repo / "app/calc.py").read_bytes() == original


def test_failed_tests_cannot_be_success(repository):
    repo, sha = repository
    with workspace(repo, sha) as (path, files):
        llm = ScriptedLLM([call("replace_file", path="app/calc.py", content="broken = True\n"),
                           call("run_tests"), {"content": "I fixed it!"}])
        report = debug(path, files, "bug", llm, EvidenceStub([1, 1]), lambda: False)
        assert not report["verified"]
        assert report["diff"]


def test_no_reproduction_is_not_verified(repository):
    repo, sha = repository
    with workspace(repo, sha) as (path, files):
        result = debug(path, files, "bug", ScriptedLLM([{"content": "fixed"}]), EvidenceStub([0]), lambda: False)
        assert not result["verified"]


@pytest.mark.parametrize("path", ["../secret.py", "/app.py", "a/../../b.py", ".env", "a\\b.py", "key.pem"])
def test_snapshot_rejects_paths(path):
    assert not safe_name(path)


def test_missing_sandbox_fails_closed(monkeypatch):
    monkeypatch.setattr("app.agent.sandbox.sys.platform", "win32")
    with pytest.raises(SandboxUnavailable):
        Sandbox().check()


def test_worker_timeout_is_terminal(client, db_session, repository, monkeypatch):
    repo, sha = repository
    owner = User(username="timeout_owner", password_hash="unused", is_active=True)
    db_session.add(owner)
    db_session.flush()
    project = Project(name="timeout", owner_id=owner.id)
    db_session.add(project)
    db_session.flush()
    task = DebugTask(project_id=project.id, requester_id=owner.id, approver_id=owner.id,
                     repository="fixture", revision=sha, reason="bug", status="queued")
    db_session.add(task)
    db_session.commit()
    monkeypatch.setenv("BUGFLOW_AGENT_REPOSITORIES", json.dumps({"fixture": {"project_id": project.id, "path": str(repo)}}))
    class TimeoutSandbox(EvidenceStub):
        def run(self, *args):
            raise ExecutionTimeout()
    run_one(lambda: Session(test_engine), sandbox=TimeoutSandbox([]))
    db_session.refresh(task)
    assert task.status == "timed_out"
