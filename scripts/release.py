"""Collect this product's installers and current documentation into release/."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = (".AppImage", ".deb", ".msi", ".exe", ".tar.gz")


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def identity():
    name = json.loads((ROOT / "tests/functional/manifest.json").read_text(encoding="utf-8"))[
        "product"
    ]
    if (ROOT / "package.json").is_file():
        version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    else:
        version = re.search(
            r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M
        )[1]
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]*", part) for part in (name, version)):
        raise ValueError("Invalid product identity")
    return name, version


def source_files():
    if not (ROOT / ".git").exists() and (ROOT / ".build-source.json").is_file():
        return json.loads((ROOT / ".build-source.json").read_text())["files"]
    return (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        )
        .decode()
        .split("\0")
    )


def source_digest():
    files = source_files()
    value = hashlib.sha256()
    for name in sorted(set(filter(None, files))):
        path = ROOT / name
        value.update(name.encode() + b"\0")
        if path.is_symlink():
            value.update(os.readlink(path).encode())
        elif path.is_file():
            value.update(bytes.fromhex(digest(path)))
        else:
            value.update(b"deleted")
    return value.hexdigest()


def prepare_candidates(platform, arch):
    fingerprint = source_digest()
    output = ROOT / ".cache/build/artifacts" / platform / arch
    marker = output / "source.json"
    if output.exists() and (
        not marker.is_file() or json.loads(marker.read_text())["sourceDigest"] != fingerprint
    ):
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"sourceDigest": fingerprint}))
    return fingerprint


def document_archive(target):
    """Copy all authored pages and their attachments, never ignored local data."""
    if not (ROOT / ".git").exists() and not (ROOT / ".build-source.json").is_file():
        raise ValueError("Documentation requires this repository or a source snapshot")
    names = {
        name
        for name in source_files()
        if name.endswith(".md") or name.startswith(("docs/", "config/examples/"))
    }
    names.update(
        (
            "README.md",
            "README.zh-CN.md",
            "LICENSE",
            "docs/release.md",
            "docs/release.zh-CN.md",
            "tests/functional/manifest.json",
            "tests/functional/requirements.txt",
        )
    )
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(names):
            original = ROOT / name
            relative = Path(name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not original.is_file()
                or any((ROOT / part).is_symlink() for part in (relative, *relative.parents))
            ):
                raise ValueError(f"Invalid documentation file: {name}")
            archive.write(original, name)


def collect(platform, arch):
    name, version = identity()
    source = ROOT / ".cache/build/artifacts" / platform / arch
    public_version = (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", public_version):
        raise ValueError("Invalid VERSION")
    destination = ROOT / "release" / public_version
    candidates = []
    for variant in sorted(source.iterdir()) if source.is_dir() else []:
        if not variant.is_dir() or variant.is_symlink():
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", variant.name):
            raise ValueError("Invalid variant")
        for extension in EXTENSIONS:
            files = [
                p
                for p in variant.glob("*" + extension)
                if not p.name.endswith(".__uninstaller.exe")
            ]
            if len(files) > 1:
                raise ValueError(f"Ambiguous installers: {variant.name}/{extension}")
            for path in files:
                if path.is_symlink() or not path.is_file() or not path.stat().st_size:
                    raise ValueError("Invalid installer")
                if extension == ".deb":
                    fields = subprocess.check_output(
                        ["dpkg-deb", "-f", str(path), "Version", "Architecture"], text=True
                    )
                    if (
                        f"Version: {version}\n" not in fields
                        or f"Architecture: {arch}\n" not in fields
                    ):
                        raise ValueError("Package version/architecture mismatch")
                elif extension == ".tar.gz":
                    with tarfile.open(path) as archive:
                        info = json.load(archive.extractfile(name + "/image.json"))
                    if info["version"] != version or info["platform"] != platform + "/" + arch:
                        raise ValueError("Container version/architecture mismatch")
                elif f"_{version}_" not in path.name:
                    raise ValueError("Installer version mismatch")
                candidates.append(
                    (
                        path,
                        f"{name}_{version}_{platform}_{arch}{extension}",
                        variant.name,
                    )
                )
    if not candidates:
        raise ValueError(
            "Build the product in .cache/build/artifacts/<platform>/<arch>/<variant>/ first"
        )
    if len({filename for _, filename, _ in candidates}) != len(candidates):
        raise ValueError("Multiple candidates have the same public package filename")
    cache = ROOT / ".cache/release"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        stage = Path(temporary) / "payload"
        stage.mkdir()
        artifacts = []
        fingerprint = source_digest()
        previous_manifest = destination / "manifest.json"
        if previous_manifest.is_file():
            previous = json.loads(previous_manifest.read_text())
            if previous["version"] == version and previous["sourceDigest"] == fingerprint:
                for record in previous["artifacts"]:
                    if record["kind"] != "installer" or (
                        record["platform"],
                        record["architecture"],
                    ) == (platform, arch):
                        continue
                    old = destination / record["file"]
                    if (
                        old.parent != destination
                        or old.is_symlink()
                        or digest(old) != record["sha256"]
                    ):
                        raise ValueError("Existing release checksum mismatch")
                    shutil.copy2(old, stage / old.name)
                    artifacts.append(record)
        for original, filename, variant in candidates:
            shutil.copy2(original, stage / filename)
            artifacts.append(
                {
                    "file": filename,
                    "bytes": original.stat().st_size,
                    "sha256": digest(original),
                    "variant": variant,
                    "kind": "installer",
                    "platform": platform,
                    "architecture": arch,
                    "deployment": "docker"
                    if variant == "container"
                    else "windows"
                    if platform == "windows"
                    else "local",
                    "source": original.relative_to(source).as_posix(),
                }
            )
        documents = stage / f"{name}_{version}_docs.zip"
        document_archive(documents)
        artifacts.append(
            {
                "file": documents.name,
                "bytes": documents.stat().st_size,
                "sha256": digest(documents),
                "kind": "document",
            }
        )
        for language in ("", ".zh-CN"):
            # Keep natural filenames too, so verbatim language links remain valid.
            for filename in (f"README{language}.md", f"release{language}.md"):
                shutil.copy2(ROOT / f"docs/release{language}.md", stage / filename)
                artifacts.append(
                    {
                        "file": filename,
                        "bytes": (stage / filename).stat().st_size,
                        "sha256": digest(stage / filename),
                        "kind": "document",
                    }
                )
        for record in list(artifacts):
            if record["kind"] == "installer":
                sidecar = stage / (record["file"] + ".sha256")
                sidecar.write_text(f"{record['sha256']}  {record['file']}\n", encoding="utf-8")
                artifacts.append(
                    {
                        "file": sidecar.name,
                        "bytes": sidecar.stat().st_size,
                        "sha256": digest(sidecar),
                        "kind": "checksum",
                    }
                )
        receipt = {
            "schemaVersion": 2,
            "product": name,
            "version": version,
            "releaseVersion": public_version,
            "sourceDigest": fingerprint,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "validation": "candidate-not-platform-certification",
            "artifacts": artifacts,
        }
        (stage / "manifest.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (stage / "SHA256SUMS").write_text(
            "".join(f"{digest(path)}  {path.name}\n" for path in sorted(stage.iterdir())),
            encoding="utf-8",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        previous = Path(temporary) / "previous"
        if destination.exists():
            destination.rename(previous)
        try:
            stage.rename(destination)
        except BaseException:
            if previous.exists():
                previous.rename(destination)
            raise
    print(destination / "manifest.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("linux", "windows"))
    parser.add_argument("--arch", choices=("amd64", "arm64"))
    parser.add_argument("--docs", type=Path, help="write only a documentation ZIP to this path")
    parser.add_argument(
        "--source-digest", action="store_true", help="print the current source fingerprint"
    )
    args = parser.parse_args()
    if args.source_digest:
        print(source_digest())
    elif args.docs:
        if args.platform or args.arch:
            parser.error("--docs cannot be combined with --platform/--arch")
        document_archive(args.docs)
    elif args.platform and args.arch:
        collect(args.platform, args.arch)
    else:
        parser.error("provide --docs or both --platform and --arch")
