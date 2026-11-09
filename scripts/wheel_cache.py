"""Persist a resolved, hash-checked Windows wheel set for offline rebuilds."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.glob("*.whl"))}


def wheelhouse(cache, requirements, python_version):
    inputs = []
    for requirement in requirements:
        path = Path(requirement)
        inputs.append([path.name, hashlib.sha256(path.read_bytes()).hexdigest()]
                      if path.is_file() else requirement)
    key = hashlib.sha256(json.dumps([inputs, python_version, "win_amd64"]).encode()).hexdigest()
    destination = cache / key
    marker = destination / "manifest.json"
    try:
        recorded = json.loads(marker.read_text())
        if recorded and recorded == hashes(destination):
            print("Reusing verified offline Windows wheels", flush=True)
            return destination
    except (OSError, ValueError):
        pass
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as directory:
        stage = Path(directory) / "wheels"
        stage.mkdir()
        subprocess.run([
            sys.executable, "-m", "pip", "download", "--dest", str(stage),
            "--platform", "win_amd64", "--python-version", python_version,
            "--only-binary=:all:", *requirements,
        ], check=True)
        files = hashes(stage)
        if not files:
            raise RuntimeError("Windows wheel download produced no wheels")
        (stage / "manifest.json").write_text(json.dumps(files, indent=2))
        if destination.exists():
            shutil.rmtree(destination)
        stage.rename(destination)
    return destination
