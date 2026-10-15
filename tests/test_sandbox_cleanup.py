"""Offline lifecycle checks; no Docker or model service is executed."""
import io
import subprocess
from unittest.mock import Mock

import pytest

from app.agent.sandbox import Sandbox, Cancelled, ExecutionTimeout


@pytest.mark.parametrize("failure", ["timeout", "oserror", "nonzero"])
@pytest.mark.parametrize("outcome", ["success", "docker_error", "cancel", "timeout", "process_error"])
def test_cleanup_failure_never_skips_process_reaping(monkeypatch, tmp_path, caplog, failure, outcome):
    process = Mock()
    process.stdout = io.BytesIO(b"bounded test output")
    process.returncode = 125 if outcome == "docker_error" else 0
    process.poll.return_value = process.returncode if outcome in {"success", "docker_error"} else None
    if outcome == "process_error":
        process.poll.side_effect = [RuntimeError("process error"), None]
    monkeypatch.setattr(Sandbox, "check", lambda self: "sha256:" + "a" * 64)
    monkeypatch.setattr("app.agent.sandbox.subprocess.Popen", lambda *a, **kw: process)
    cleanup = Mock(return_value=subprocess.CompletedProcess([], 1))
    if failure == "timeout":
        cleanup.side_effect = subprocess.TimeoutExpired("docker", 10)
    elif failure == "oserror":
        cleanup.side_effect = OSError("docker unavailable")
    monkeypatch.setattr("app.agent.sandbox.subprocess.run", cleanup)
    if outcome == "timeout":
        ticks = iter([0, 61])
        monkeypatch.setattr("app.agent.sandbox.time.monotonic", lambda: next(ticks))
    expected = {"cancel": Cancelled, "timeout": ExecutionTimeout, "process_error": RuntimeError}
    caught = None
    try:
        Sandbox().run(tmp_path, [], lambda: outcome == "cancel")
    except Exception as error:
        caught = error
    process.wait.assert_called_once_with(timeout=5)
    assert process.stdout.closed
    if outcome not in {"success", "docker_error"}:
        process.kill.assert_called_once()
    if outcome in expected:
        assert isinstance(caught, expected[outcome])
    else:
        assert caught is not None and type(caught).__name__ == "SandboxCleanupError"
    assert "Sandbox cleanup incomplete" in caplog.text


def test_popen_failure_still_attempts_container_removal(monkeypatch, tmp_path):
    monkeypatch.setattr(Sandbox, "check", lambda self: "sha256:" + "a" * 64)
    start = Mock(side_effect=OSError("cannot start docker"))
    cleanup = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr("app.agent.sandbox.subprocess.Popen", start)
    monkeypatch.setattr("app.agent.sandbox.subprocess.run", cleanup)
    with pytest.raises(OSError):
        Sandbox().run(tmp_path, [], lambda: False)
    cleanup.assert_called_once()
    assert cleanup.call_args.args[0][:3] == ["docker", "rm", "-f"]


@pytest.mark.parametrize("exit_code", [0, 1, 125])
def test_normal_cleanup_preserves_test_exit_code(monkeypatch, tmp_path, exit_code):
    process = Mock()
    process.stdout = io.BytesIO(b"test result")
    process.returncode = exit_code
    process.poll.return_value = exit_code
    start = Mock(return_value=process)
    cleanup = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(Sandbox, "check", lambda self: "sha256:" + "a" * 64)
    monkeypatch.setattr("app.agent.sandbox.subprocess.Popen", start)
    monkeypatch.setattr("app.agent.sandbox.subprocess.run", cleanup)
    result = Sandbox().run(tmp_path, [], lambda: False)
    assert result == {"exit_code": exit_code, "output": "test result"}
    assert "--rm" not in start.call_args.args[0]  # One explicit cleanup owns removal.
    cleanup.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)
    process.kill.assert_not_called()
    assert process.stdout.closed


def test_kill_error_still_waits_and_preserves_cancellation(monkeypatch, tmp_path, caplog):
    process = Mock()
    process.stdout = io.BytesIO(b"")
    process.poll.return_value = None
    process.kill.side_effect = OSError("already exited")
    monkeypatch.setattr(Sandbox, "check", lambda self: "sha256:" + "a" * 64)
    monkeypatch.setattr("app.agent.sandbox.subprocess.Popen", lambda *a, **kw: process)
    monkeypatch.setattr("app.agent.sandbox.subprocess.run",
                        lambda *a, **kw: subprocess.CompletedProcess([], 0))
    with pytest.raises(Cancelled):
        Sandbox().run(tmp_path, [], lambda: True)
    process.wait.assert_called_once_with(timeout=5)
    assert process.stdout.closed
    assert "Sandbox cleanup incomplete" in caplog.text


def test_reader_start_error_still_reaps_process(monkeypatch, tmp_path):
    process = Mock()
    process.stdout = io.BytesIO(b"")
    process.poll.return_value = None
    monkeypatch.setattr(Sandbox, "check", lambda self: "sha256:" + "a" * 64)
    monkeypatch.setattr("app.agent.sandbox.subprocess.Popen", lambda *a, **kw: process)
    monkeypatch.setattr("app.agent.sandbox.subprocess.run",
                        lambda *a, **kw: subprocess.CompletedProcess([], 0))
    monkeypatch.setattr("app.agent.sandbox.threading.Thread.start",
                        Mock(side_effect=RuntimeError("reader start failed")))
    with pytest.raises(RuntimeError, match="reader start failed"):
        Sandbox().run(tmp_path, [], lambda: False)
    process.kill.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)
    assert process.stdout.closed
