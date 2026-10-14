import json
import pytest
from app.agent.llm import ModelError
from app.agent.models import DebugTask
from app.main import app
from app.routers.agent import get_llm


class ScriptedLLM:
    """Test double only; never used by the production dependency."""
    def __init__(self, replies):
        self.replies = iter(replies)
        self.messages = []

    def complete(self, messages, tools):
        self.messages = list(messages)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def call(name, **args):
    return {"tool_calls": [{"id": "call1", "type": "function",
                           "function": {"name": name, "arguments": json.dumps(args)}}]}


@pytest.fixture
def identity(client):
    def create(name):
        r = client.post("/auth/register", json={"username": name, "password": "securepass123"})
        assert r.status_code == 201
        token = client.post("/auth/login", json={"username": name, "password": "securepass123"}).json()["access_token"]
        return r.json(), {"Authorization": f"Bearer {token}"}
    return create


@pytest.fixture
def context(client, identity):
    owner, headers = identity("agent_owner")
    project = client.post("/projects", json={"name": "agent project"}, headers=headers).json()
    return owner, headers, project


@pytest.fixture
def model():
    def install(*replies):
        llm = ScriptedLLM(replies)
        app.dependency_overrides[get_llm] = lambda: llm
        return llm
    yield install
    app.dependency_overrides.pop(get_llm, None)


def test_query_real_project(client, context, model):
    _, headers, p = context
    llm = model(call("get_project"), {"content": "done"})
    r = client.post("/agent/chat", json={"project_id": p["id"], "message": "project?"}, headers=headers)
    assert r.status_code == 200
    assert json.loads(llm.messages[-1]["content"])["name"] == "agent project"
    trace = client.get("/agent/traces/" + r.json()["trace_id"], headers=headers).json()
    assert trace["events"] == [{"step": 0, "tool": "get_project", "ok": True}]


@pytest.mark.parametrize("tool,args", [("get_issue", {"issue_id": 999}), ("approve", {}),
                                       ("request_debug", {"repository": "C:/arbitrary", "reason": "fix"})])
def test_tool_failures_are_observations(client, context, model, tool, args):
    _, h, p = context
    llm = model(call(tool, **args), {"content": "rejected"})
    r = client.post("/agent/chat", json={"project_id": p["id"], "message": "test"}, headers=h)
    assert r.status_code == 200
    assert "error" in json.loads(llm.messages[-1]["content"])


def test_outsider_cannot_query(client, context, identity):
    _, _, p = context
    _, h = identity("agent_outsider")
    assert client.post("/agent/chat", json={"project_id": p["id"], "message": "show"}, headers=h).status_code == 403


def test_model_failure(client, context, model):
    _, h, p = context
    model(ModelError("provider secret must not escape"))
    r = client.post("/agent/chat", json={"project_id": p["id"], "message": "show"}, headers=h)
    assert r.status_code == 502
    assert "provider secret" not in r.text


def test_authorization_state_machine(client, context, identity, db_session):
    owner, h, p = context
    member, mh = identity("agent_member")
    client.post(f"/projects/{p['id']}/members", json={"username": member["username"]}, headers=h)
    task = DebugTask(project_id=p["id"], requester_id=member["id"], repository="repo", revision="a" * 40, reason="bug")
    db_session.add(task)
    db_session.commit()
    url = f"/agent/tasks/{task.id}"
    data = {"authorize_code_execution": True, "revision": task.revision}
    assert client.post(url + "/approve", json=data, headers=mh).status_code == 403
    assert client.post(url + "/approve", json={**data, "authorize_code_execution": False}, headers=h).status_code == 422
    assert client.post(url + "/approve", json=data, headers=h).status_code == 200
    assert client.post(url + "/approve", json=data, headers=h).status_code == 409
    assert client.post(url + "/cancel", headers=h).status_code == 200
    assert client.get(url, headers=h).json()["status"] == "cancelled"
