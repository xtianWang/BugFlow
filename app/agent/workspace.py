from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import tempfile
from app.agent.repositories import git, RepositoryError


def safe_name(name):
    p = PurePosixPath(name)
    return (not p.is_absolute() and not any(x in {"..", "."} or x.startswith(".") for x in p.parts)
            and "\\" not in name and ":" not in name
            and p.suffix in {".py", ".md", ".toml", ".txt"}
            and not any(x in name.lower() for x in ("secret", "credential", "token", "password", "private")))


@contextmanager
def workspace(repo, revision):
    with tempfile.TemporaryDirectory(prefix="bugflow-agent-") as root:
        path = Path(root) / "worktree"
        # No checkout: repository filters/hooks must never execute on the host.
        git(repo, "worktree", "add", "--detach", "--no-checkout", str(path), revision)
        try:
            git(path, "read-tree", revision)
            files = []
            total = 0
            for entry in git(repo, "ls-tree", "-r", "-z", revision).split("\0"):
                if not entry:
                    continue
                info, name = entry.split("\t", 1)
                mode, kind, oid = info.split()
                if mode not in {"100644", "100755"} or kind != "blob" or not safe_name(name):
                    continue
                size = int(git(repo, "cat-file", "-s", oid))
                total += size
                if size > 100_000 or total > 2_000_000 or len(files) >= 200:
                    raise RepositoryError("Repository snapshot exceeds V1 budget")
                content = git(repo, "cat-file", "blob", oid)
                target = path / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="")
                files.append(name)
            yield path, files
        finally:
            git(repo, "worktree", "remove", "--force", str(path))


def diff(path, files):
    if not files:
        return ""
    result = git(path, "diff", "--no-ext-diff", "--no-textconv", "HEAD", "--", *files)
    if len(result) > 100_000:
        raise RepositoryError("Patch exceeds review budget")
    return result
