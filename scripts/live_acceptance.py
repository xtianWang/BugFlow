"""Opt-in REAL LLM + runsc repair acceptance, using only disposable data.

Run inside Linux from the repository root. --config-stdin accepts configuration
without putting credentials in command arguments or files. Only a scrubbed report
is printed; no production database is used.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-stdin", action="store_true")
    args = parser.parse_args()
    if args.config_stdin:
        config = json.loads(sys.stdin.readline())
        for name in ("BUGFLOW_LLM_API_KEY", "BUGFLOW_LLM_MODEL", "BUGFLOW_LLM_BASE_URL", "BUGFLOW_SANDBOX_IMAGE"):
            if config.get(name):
                os.environ[name] = config[name]
    os.environ["BUGFLOW_LLM_THINKING"] = "disabled"
    os.environ["BUGFLOW_SECRET_KEY"] = secrets.token_hex(32)
    os.environ["BUGFLOW_DATABASE_URL"] = "sqlite://"

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool
    from app.database import Base, get_db
    from app.main import app
    from app.agent.llm import LLM, contains_credential
    from app.agent.sandbox import Sandbox
    from app.agent.worker import run_one
    from app.routers.agent import get_llm

    sandbox = Sandbox()
    sandbox.check()
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)
    def override_db():
        with Session(test_engine) as session:
            yield session
    llm = LLM()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        with tempfile.TemporaryDirectory(prefix="bugflow-live-fixture-") as temp, TestClient(app) as client:
            repo = Path(temp)
            (repo / "app").mkdir()
            (repo / "app/__init__.py").write_text("")
            (repo / "app/calc.py").write_text("def add(a, b):\n    return a - b\n")
            (repo / "test_calc.py").write_text(
                "from app.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
                "    assert add(-2, 3) == 1\n    assert add(0, 0) == 0\n")
            def git(*argv):
                return subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True)
            git("init")
            git("add", ".")
            git("-c", "user.name=AcceptanceFixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "known bug")
            original = (repo / "app/calc.py").read_bytes()

            def account(name):
                r = client.post("/auth/register", json={"username": name, "password": "live-test-only-123"})
                assert r.status_code == 201
                token = client.post("/auth/login", json={"username": name, "password": "live-test-only-123"}).json()["access_token"]
                return r.json(), {"Authorization": "Bearer " + token}
            owner, headers = account("live_owner")
            member, mh = account("live_member")
            _, outsider = account("live_outsider")
            p = client.post("/projects", json={"name": "Live acceptance"}, headers=headers).json()
            assert client.post(f"/projects/{p['id']}/members", json={"username": member["username"]}, headers=headers).status_code == 201
            issue = client.post(f"/projects/{p['id']}/issues", json={"title": "Addition returns -1 instead of 5",
                "description": "In app/calc.py, add(2,3) should return 5 but returns -1. Please investigate."}, headers=headers).json()
            os.environ["BUGFLOW_AGENT_REPOSITORIES"] = json.dumps({"acceptance-fixture": {"project_id": p["id"], "path": str(repo)}})
            question = (f"Read the current project and Issue {issue['id']} using tools. Decide if source debugging is needed. "
                        "If needed, propose Debug for repository alias acceptance-fixture; do not claim authorization.")
            result = client.post("/agent/chat", json={"project_id": p["id"], "message": question}, headers=headers)
            if result.status_code != 200:
                print(json.dumps({"passed": False, "stage": "chat", "error": result.json()}))
                return 1
            task_ids = result.json()["debug_task_ids"]
            if not task_ids:
                print(json.dumps({"passed": False, "stage": "model_did_not_propose_debug"}))
                return 1
            url = "/agent/tasks/" + task_ids[0]
            task = client.get(url, headers=headers).json()
            assert task["status"] == "awaiting_authorization"
            assert client.get(url, headers=outsider).status_code == 403
            approval = {"authorize_code_execution": True, "revision": task["revision"]}
            assert client.post(url + "/approve", json=approval, headers=mh).status_code == 403
            assert client.post(url + "/approve", json=approval, headers=headers).status_code == 200
            run_one(lambda: Session(test_engine), llm=llm, sandbox=sandbox)
            completed = client.get(url, headers=headers).json()
            untouched = (repo / "app/calc.py").read_bytes() == original
            report = {"passed": completed["status"] == "succeeded" and untouched,
                      "status": completed["status"], "original_unchanged": untouched,
                      "report": completed["report"]}
            if report["passed"]:
                assert client.post(url + "/review", json={"decision": "accepted"}, headers=headers).status_code == 200
            if contains_credential(report, os.environ["BUGFLOW_LLM_API_KEY"]):
                print('{"passed":false,"error":"secret_echo_blocked"}')
                return 1
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["passed"] else 1
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_llm, None)
        Base.metadata.drop_all(test_engine)
        test_engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
