"""Capture the actual compiler inputs before a potentially long generation."""

import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def file_identity(path):
    path = Path(path).resolve()
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": checksum}


def generated_identity(directory):
    """Bind publication to generated sources, independently of staging paths."""
    directory = Path(directory)
    files = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.name != "generation-identity.json" and (
                path.suffix in (".cpp", ".hpp", ".c", ".h", ".json") or path.name == "Makefile"):
            identity = file_identity(path)
            files[str(path.relative_to(directory))] = {key: identity[key] for key in ("bytes", "sha256")}
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"files": files, "sha256": hashlib.sha256(payload).hexdigest()}


def source_identity(root=ROOT):
    """Include dirty/untracked sources; a commit alone is not source identity."""
    root = Path(root).resolve()
    files, repositories = {}, {}
    for base, paths in ((root, ("Makefile", "scripts")),
                        (root / "wolvrix", ("CMakeLists.txt", "include", "lib", "app"))):
        if not base.is_dir():
            continue
        head = subprocess.check_output(["git", "-C", str(base), "rev-parse", "HEAD"], text=True).strip()
        names = subprocess.check_output(
            ["git", "-C", str(base), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *paths]
        ).decode().split("\0")
        repositories[str(base.relative_to(root))] = head
        for name in sorted(set(names) - {""}):
            path = base / name
            key = str(path.relative_to(root))
            if path.is_file():
                files[key] = file_identity(path)["sha256"]
            elif not path.exists():
                files[key] = None
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {"repositories": repositories, "files_sha256": files,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "scope": "root Makefile/scripts and wolvrix CMakeLists/include/lib/app; dependencies identified by loaded binaries"}


def loaded_libraries():
    """Read mapped paths, rather than guessing a build/install directory."""
    paths = set()
    for line in Path("/proc/self/maps").read_text().splitlines():
        fields = line.split(None, 5)
        if len(fields) != 6 or not fields[5].startswith("/"):
            continue
        path = fields[5]
        if "_wolvrix" not in path and "libwolvrix" not in path:
            continue
        if path.endswith(" (deleted)"):
            raise RuntimeError("Loaded compiler binary has been replaced; restart generation to capture a valid identity")
        paths.add(path)
    return [file_identity(path) for path in sorted(paths)]


def capture_generation(kind, *, inputs=None, configuration=None):
    return {"schema": "wolvrix.grhsim.generation-identity.v1", "kind": kind,
            "sources": source_identity(), "loaded_libraries": loaded_libraries(),
            "python": {"executable": sys.executable, "version": platform.python_version()},
            "inputs": {name: file_identity(path) for name, path in sorted((inputs or {}).items())},
            "configuration": configuration or {}}


def write_identity(path, identity):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".pending")
    temporary.write_text(json.dumps(identity, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(path)
