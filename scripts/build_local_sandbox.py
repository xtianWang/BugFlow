"""Provision a local test image from trusted Ubuntu Python packages, without Docker Hub.

Run with the dedicated Linux venv. No repository code, home directory or credentials
are included. This builds an operator-owned image, never a model-supplied Dockerfile.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile


def main():
    if sys.platform != "linux":
        raise SystemExit("Run this provisioner inside the dedicated Ubuntu environment")
    with tempfile.TemporaryDirectory(prefix="bugflow-image-build-") as temp:
        root = Path(temp) / "rootfs"
        root.mkdir()
        copied = set()
        def copy_binary(source, destination=None):
            source = Path(source).resolve()
            target = root / (destination or str(source).lstrip("/"))
            if source in copied and destination is None:
                return
            copied.add(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            result = subprocess.run(["ldd", str(source)], capture_output=True, text=True)
            for library in re.findall(r"(?:=>\s+)?(/[^\s()]+)", result.stdout):
                lib = Path(library)
                dest = root / str(lib).lstrip("/")
                if lib.is_file() and not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(lib.resolve(), dest)
        copy_binary(sys.executable, "usr/bin/python3")
        (root / "usr/bin/python").symlink_to("python3")
        copy_binary("/bin/dash", "bin/sh")
        copy_binary("/usr/bin/cp", "bin/cp")
        stdlib = Path(sysconfig.get_path("stdlib"))
        target = root / str(stdlib).lstrip("/")
        shutil.copytree(stdlib, target, ignore=shutil.ignore_patterns("__pycache__", "test", "tests"))
        for library in stdlib.rglob("*.so"):
            copy_binary(library)
        site = Path(sysconfig.get_path("purelib"))
        shutil.copytree(site, root / "opt/site-packages", ignore=shutil.ignore_patterns("__pycache__"))
        for library in site.rglob("*.so"):
            copy_binary(library)
        (root / "tmp").mkdir(mode=0o1777)
        archive = Path(temp) / "rootfs.tar"
        with tarfile.open(archive, "w") as tar:
            for path in sorted(root.iterdir()):
                tar.add(path, arcname=path.name)
        result = subprocess.run(["docker", "import", "--change", "ENV PYTHONPATH=/opt/site-packages",
                                 str(archive), "bugflow-sandbox:local"], capture_output=True, text=True, check=True)
        image_id = result.stdout.strip()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
            raise RuntimeError("Docker did not return a full content-addressed image ID")
        print(image_id)


if __name__ == "__main__":
    main()
