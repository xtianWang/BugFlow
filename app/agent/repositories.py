import json
import os
from pathlib import Path
import re
import subprocess


class RepositoryError(RuntimeError):
    pass


def git(path, *args):
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    try:
        result = subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
            "-c", "core.fsmonitor=false", "-C", str(path), *args],
            env=env, capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        raise RepositoryError("Git unavailable or timed out") from None
    if result.returncode:
        raise RepositoryError("Git operation failed")
    return result.stdout.decode("utf-8", errors="strict")


def binding(project_id, repository):
    # Only operators populate the registry. API clients never supply filesystem paths.
    try:
        item = json.loads(os.getenv("BUGFLOW_AGENT_REPOSITORIES", "{}"))[repository]
        if item["project_id"] != project_id:
            raise ValueError()
        path = Path(item["path"]).resolve(strict=True)
        if Path(git(path, "rev-parse", "--show-toplevel").strip()).resolve() != path:
            raise ValueError()
        return path
    except (KeyError, TypeError, ValueError, OSError):
        raise RepositoryError("Repository is not explicitly authorized for this project") from None


def revision(path):
    value = git(path, "rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", value):
        raise RepositoryError("Invalid repository revision")
    return value
