"""Real runtime checks; no LLM or real database. Run inside the dedicated Linux host."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent.sandbox import Sandbox, Cancelled, ExecutionTimeout

TEST = '''import os, socket
def test_security():
    assert os.getuid() == 65534
    assert "BUGFLOW_LLM_API_KEY" not in os.environ
    assert not os.path.exists("/mnt/d/Projects/BugFlow")
    assert not os.path.exists("/var/run/docker.sock")
    for target in ("/src/probe-write", "/probe-write"):
        try:
            open(target, "w").close()
        except OSError:
            pass
        else:
            raise AssertionError("filesystem is writable")
    s = socket.socket()
    s.settimeout(2)
    assert s.connect_ex(("1.1.1.1", 443)) != 0
    s.close()
    status = open("/proc/self/status").read()
    assert "CapEff:\\t0000000000000000" in status
'''


def main():
    sandbox = Sandbox()
    sandbox.check()
    results = {}
    with tempfile.TemporaryDirectory(prefix="bugflow-runtime-check-") as temp:
        path = Path(temp)
        test = path / "test_runtime.py"
        test.write_text(TEST)
        evidence = sandbox.run(path, [test.name], lambda: False)
        results["security"] = evidence
        assert evidence["exit_code"] == 0, evidence["output"]
        try:
            sandbox.run(path, [test.name], lambda: True)
        except Cancelled:
            results["cancelled"] = True
        test.write_text("import time\ndef test_sleep():\n    time.sleep(90)\n")
        start = time.monotonic()
        try:
            sandbox.run(path, [test.name], lambda: False)
        except ExecutionTimeout:
            results["timeout_seconds"] = round(time.monotonic() - start, 1)
        assert results.get("cancelled") and "timeout_seconds" in results
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
