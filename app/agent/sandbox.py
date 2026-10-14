import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4


class SandboxUnavailable(RuntimeError):
    pass


class ExecutionTimeout(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


class Sandbox:
    """Fail closed: Linux + runsc + pinned prebuilt dependency image required."""
    def check(self):
        image = os.getenv("BUGFLOW_SANDBOX_IMAGE", "")
        if sys.platform != "linux" or not shutil.which("docker"):
            raise SandboxUnavailable("Linux Docker with runsc is required; host execution is disabled")
        if not re.fullmatch(r"(?:[\w./:-]+@sha256:|sha256:)[a-f0-9]{64}", image):
            raise SandboxUnavailable("A prebuilt image pinned by digest or full local sha256 image ID is required")
        result = subprocess.run(["docker", "info", "--format", "{{json .Runtimes}}"],
                                capture_output=True, timeout=10, text=True)
        if result.returncode or "runsc" not in json.loads(result.stdout):
            raise SandboxUnavailable("runsc runtime is not available")
        inspected = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                                   capture_output=True, timeout=10, text=True)
        if inspected.returncode or not re.fullmatch(r"sha256:[a-f0-9]{64}", inspected.stdout.strip()):
            raise SandboxUnavailable("Pinned image must already exist locally")
        return image

    def run(self, path, files, cancelled):
        image = self.check()
        name = "bugflow-" + uuid4().hex
        # Only the filtered source snapshot is mounted, never .git or user home.
        with tempfile.TemporaryDirectory(prefix="bugflow-snapshot-") as root:
            snapshot = Path(root)
            for filename in files:
                target = snapshot / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((path / filename).read_bytes())
            snapshot.chmod(0o755)
            command = ["docker", "run", "--rm", "--pull=never", "--name", name,
                       "--runtime=runsc", "--network=none", "--read-only", "--cap-drop=ALL",
                       "--security-opt=no-new-privileges", "--user=65534:65534",
                       "--pids-limit=64", "--memory=512m", "--memory-swap=512m", "--cpus=1",
                       "--ulimit", "nofile=128:128", "--log-driver=none",
                       "--tmpfs", "/work:rw,nosuid,nodev,size=64m,mode=1777",
                       "--tmpfs", "/tmp:rw,nosuid,nodev,size=32m,mode=1777",
                       "--mount", f"type=bind,src={snapshot},dst=/src,readonly",
                       "--env", "BUGFLOW_SECRET_KEY=isolated-test-only-secret-at-least-32-bytes",
                       "--env", "BUGFLOW_DATABASE_URL=sqlite://", "--entrypoint=/bin/sh", image,
                       "-c", "cp -R /src/. /work/ && cd /work && python -m pytest -q -p no:cacheprovider"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            output = bytearray()
            def drain():
                while chunk := process.stdout.read(4096):
                    if len(output) < 16_000:
                        output.extend(chunk[:16_000 - len(output)])
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            deadline = time.monotonic() + 60
            try:
                while process.poll() is None:
                    if cancelled():
                        raise Cancelled("Task cancelled")
                    if time.monotonic() > deadline:
                        raise ExecutionTimeout("Sandbox test exceeded 60 seconds")
                    time.sleep(0.1)
                reader.join(timeout=2)
                return {"exit_code": process.returncode, "output": output.decode("utf-8", "replace")}
            finally:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                process.stdout.close()
