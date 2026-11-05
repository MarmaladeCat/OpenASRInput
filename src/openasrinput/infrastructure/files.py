"""Reversible package activation; only files owned by this application are managed."""

import hashlib
import json
import os
import stat
import tempfile
import time
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import atomic_json


def fingerprint(path):
    path = Path(path)
    if path.is_symlink():
        return "link:" + os.readlink(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def private_write(path, data, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), mode)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def request_bytes(url, key=None, method="GET", body=None, timeout=5):
    class NoRedirects(HTTPRedirectHandler):
        def redirect_request(self, request, file, code, message, headers, new_url):
            return None

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    request = Request(
        url,
        headers=headers,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
    )
    with build_opener(NoRedirects()).open(request, timeout=timeout) as response:
        return response.read()


def api(url, key=None, method="GET", body=None, timeout=5):
    return json.loads(request_bytes(url, key, method, body, timeout))


class FileTransaction:
    def __init__(self, state):
        self.state = Path(state)
        self.path = self.state / "installation.json"
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state, 0o700)
        self.manifest = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {
                "version": 1,
                "active": False,
                "files": {},
                "createdAt": time.time(),
            }
        )

    def commit(self):
        atomic_json(self.path, self.manifest)

    def write(self, path, data, mode=0o600):
        path = Path(path)
        key = str(path)
        if key not in self.manifest["files"]:
            backup = self.state / "before" / str(len(self.manifest["files"]))
            record = {
                "path": key,
                "existed": path.exists() or path.is_symlink(),
                "link": os.readlink(path) if path.is_symlink() else None,
                "originalMode": stat.S_IMODE(path.stat().st_mode) if path.exists() else None,
                "backup": str(backup),
                "installedHash": None,
            }
            if path.is_file() and not path.is_symlink():
                private_write(backup, path.read_bytes())
            self.manifest["files"][key] = record
            self.commit()
        private_write(path, data, mode)
        self.manifest["files"][key]["installedHash"] = fingerprint(path)
        self.commit()

    def restore(self):
        retained = []
        for number, record in enumerate(reversed(list(self.manifest["files"].values()))):
            path = Path(record["path"])
            current = fingerprint(path)
            if current is not None and current != record["installedHash"]:
                archive = self.state / "retained-after-activation" / str(number)
                if path.is_symlink():
                    private_write(archive, os.readlink(path).encode())
                elif path.is_file():
                    private_write(archive, path.read_bytes())
                retained.append({"originalPath": str(path), "archive": str(archive)})
            if record["existed"]:
                if record["link"] is not None:
                    if path.exists() or path.is_symlink():
                        path.unlink()
                    path.symlink_to(record["link"])
                else:
                    private_write(path, Path(record["backup"]).read_bytes(), record["originalMode"])
            elif path.exists() or path.is_symlink():
                path.unlink()
        self.manifest["active"] = False
        self.manifest["retained"] = retained
        self.manifest["rolledBackAt"] = time.time()
        self.commit()
        return retained
