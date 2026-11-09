"""Reuse a frozen runtime only when its inputs, toolchain and payload match."""

import hashlib
import json
import os
import platform
import stat
import sys
from pathlib import Path


def inventory(directory):
    rows = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            content = "link:" + os.readlink(path)
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            content = digest.hexdigest()
        else:
            continue
        rows.append([path.relative_to(directory).as_posix(), content,
                     stat.S_IMODE(path.lstat().st_mode)])
    return rows


def fingerprint(root):
    image = os.environ.get("OPENASR_BUILD_IMAGE")
    if not image:
        return None  # Ad-hoc environments do not have a verified immutable identity.
    rows = []
    for folder in ("src", "packaging"):
        rows += [[folder + "/" + name, content, mode]
                 for name, content, mode in inventory(root / folder)
                 if "__pycache__" not in Path(name).parts and not name.endswith(".pyc")]
    for name in ("VERSION", "pyproject.toml", "requirements.txt",
                 "scripts/build_runtime.py", "scripts/runtime_cache.py"):
        path = root / name
        if path.is_file():
            rows.append([name, hashlib.sha256(path.read_bytes()).hexdigest()])
    return hashlib.sha256(json.dumps([image, sys.version, platform.machine(), rows],
                                    sort_keys=True).encode()).hexdigest()


def reusable(marker, key, output):
    if key is None or not marker.is_file() or not output.is_dir():
        return False
    try:
        record = json.loads(marker.read_text())
        return record["key"] == key and bool(record["files"]) and record["files"] == inventory(output)
    except (OSError, ValueError, KeyError):
        return False


def record(marker, key, output):
    if key is not None:
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(json.dumps({"key": key, "files": inventory(output)}))
        temporary.replace(marker)
