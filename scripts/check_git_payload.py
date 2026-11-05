"""Audit Git-visible source files only; never enumerate ignored runtime stores."""

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".deb", ".pem", ".key"}
SECRET = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\basr_[A-Za-z0-9_-]{40,}\b")


def audit(root):
    visible = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root
    )
    problems = []
    count = 0
    for raw in visible.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode())
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        count += 1
        if relative.suffix in FORBIDDEN_SUFFIXES or relative.name in {
            ".env",
            "credentials.json",
            "input.local.json",
            "portal-connection.json",
        }:
            problems.append(str(relative))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        if SECRET.search(text):
            problems.append(str(relative))
    if problems:
        raise RuntimeError("Git-visible runtime/secret material: " + ", ".join(problems))
    print(f"Git payload passed: {root.name}, {count} source files")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", type=Path, nargs="*", default=[ROOT])
    args = parser.parse_args()
    for root in args.roots:
        audit(root.resolve())


if __name__ == "__main__":
    main()
