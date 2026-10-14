"""Opt-in LIVE query eval; requires a running initialized API and real model key."""
import json
import os
import httpx


def main():
    token = os.environ["BUGFLOW_EVAL_TOKEN"]
    project = int(os.environ["BUGFLOW_EVAL_PROJECT_ID"])
    base = os.getenv("BUGFLOW_EVAL_API", "http://127.0.0.1:8000")
    cases = [("project", "Please use get_project to retrieve this project.", "get_project"),
             ("members", "Please retrieve the real project members.", "get_members"),
             ("search", "Please search Issues whose title contains bug.", "search_issues")]
    with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"},
                      timeout=600, trust_env=False) as client:
        results = []
        for name, question, expected in cases:
            response = client.post("/agent/chat", json={"project_id": project, "message": question})
            passed = False
            if response.status_code == 200:
                trace = client.get("/agent/traces/" + response.json()["trace_id"])
                if trace.status_code == 200:
                    passed = any(e["tool"] == expected and e["ok"] for e in trace.json()["events"])
            results.append({"case": name, "passed": passed, "http_status": response.status_code})
    print(json.dumps({"kind": "live-query-eval", "results": results}, indent=2))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
