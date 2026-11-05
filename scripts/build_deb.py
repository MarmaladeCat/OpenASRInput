"""Build a clean binary deb; exclude all runtime data, credentials and venvs."""

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from package_gnome import package_extensions

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(
    1
)


def build_unified(output, native_build=None, runtime_dir=None):
    """Combine independently built adapters, keeping framework libraries optional."""
    output.mkdir(parents=True, exist_ok=True)
    work = Path(os.environ.get("OPENASRINPUT_BUILD_DIR", ROOT / "build"))
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="unified-", dir=work) as directory:
        root = Path(directory)
        stage = root / "stage"
        dependencies = set()
        optional = set()
        for framework in ("fcitx4", "fcitx5"):
            package = build(
                root / framework,
                framework,
                (native_build or ROOT / "build") / framework,
                runtime_dir,
            )
            extracted = root / (framework + "-stage")
            subprocess.run(["dpkg-deb", "-R", str(package), str(extracted)], check=True)
            control = (extracted / "DEBIAN/control").read_text()
            depends = next(
                line[9:] for line in control.splitlines() if line.startswith("Depends: ")
            )
            for dependency in depends.split(", "):
                if dependency.startswith(("fcitx", "libfcitx")):
                    optional.add(dependency)
                else:
                    dependencies.add(dependency)
            shutil.copytree(extracted, stage, dirs_exist_ok=True)
        # GI binds to the system libibus; ASR remains in the private runtime.
        dependencies.update(("python3", "python3-gi", "gir1.2-ibus-1.0"))
        shutil.copytree(
            ROOT / "src/native/ibus",
            stage / "usr/lib/openasrinput/ibus",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        registry = stage / "usr/share/ibus/component"
        registry.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "src/native/ibus/openasrinput.xml", registry)
        panel = (native_build or ROOT / "build") / "fcitx5/voice-panel"
        if not panel.is_file():
            raise RuntimeError("Build the standalone voice-panel target before unified packaging")
        destination = stage / "usr/lib/openasrinput/ibus/voice-panel"
        shutil.copy2(panel, destination)
        destination.chmod(0o755)
        # The shared renderer uses the small Fcitx utility/event-loop library,
        # not a Fcitx daemon. Bundle it privately so IBus does not install Fcitx.
        private = destination.parent / "panel-libs"
        private.mkdir()
        shlibs = []
        linkage = subprocess.check_output(["ldd", str(panel)], text=True)
        for line in linkage.splitlines():
            parts = line.split()
            if (
                len(parts) >= 3
                and parts[1] == "=>"
                and parts[0].startswith(("libFcitx5", "libicu"))
            ):
                shutil.copy2(Path(parts[2]).resolve(), private / parts[0])
                subprocess.run(
                    ["patchelf", "--set-rpath", "$ORIGIN", str(private / parts[0])], check=True
                )
                name, version = parts[0].split(".so.")
                shlibs.append(f"{name} {version} openasrinput\n")
        subprocess.run(
            ["patchelf", "--set-rpath", "$ORIGIN/panel-libs", str(destination)], check=True
        )
        metadata = stage / "debian"
        metadata.mkdir()
        (metadata / "control").write_text(
            "Source: openasrinput\n\nPackage: openasrinput\nArchitecture: any\n"
        )
        (metadata / "shlibs.local").write_text("".join(shlibs))
        needed = subprocess.check_output(
            [
                "dpkg-shlibdeps",
                "-O",
                "-xopenasrinput",
                "-l" + str(private),
                "-e" + str(destination),
                *("-e" + str(path) for path in private.iterdir()),
            ],
            cwd=stage,
            text=True,
        )
        for line in needed.splitlines():
            if line.startswith("shlibs:Depends="):
                dependencies.update(line.split("=", 1)[1].split(", "))
        shutil.rmtree(metadata)
        (stage / "usr/lib/openasrinput/framework").write_text("auto\n")
        lines = []
        for line in control.splitlines():
            if line.startswith("Depends:"):
                line = "Depends: " + ", ".join(sorted(dependencies))
            elif line.startswith("Description:"):
                line = "Description: Cursor dictation with IBus, Fcitx4 and Fcitx5"
            lines.append(line)
        lines.append("Suggests: ibus, " + ", ".join(sorted(optional)))
        (stage / "DEBIAN/control").write_text("\n".join(lines) + "\n")
        package = output / package.name
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(stage), str(package)], check=True
        )
    return package


def build(output, framework="auto", native_build=None, runtime_dir=None):
    if framework == "auto":
        return build_unified(output, native_build, runtime_dir)
    output.mkdir(parents=True, exist_ok=True)
    native_build = native_build or ROOT / "build" / framework
    filename = "libopenasrinput.so" if framework == "fcitx5" else "fcitx-openasrinput.so"
    library = native_build / "lib" / filename
    if not library.exists():
        raise RuntimeError("Build the native addon first")
    architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    work = Path(os.environ.get("OPENASRINPUT_BUILD_DIR", ROOT / "build"))
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deb-", dir=work) as directory:
        stage = Path(directory)
        app = stage / "usr/lib/openasrinput/openasrinput"
        if runtime_dir:
            shutil.copytree(runtime_dir, app.parent / "runtime")
        else:
            shutil.copytree(
                ROOT / "src/openasrinput",
                app,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        (app.parent / "framework").write_text(framework + "\n")
        binary = stage / "usr/bin/openasrinput"
        binary.parent.mkdir(parents=True)
        if runtime_dir:
            binary.write_text(
                '#!/bin/sh\nAPP_ROOT="${OPENASRINPUT_APP_ROOT:-/usr/lib/openasrinput}"\n'
                'exec "$APP_ROOT/runtime/openasrinput-runtime" "$@"\n'
            )
        else:
            shutil.copy2(ROOT / "packaging/openasrinput", binary)
        binary.chmod(0o755)
        addon = (
            stage
            / f"usr/lib/{subprocess.check_output(['dpkg-architecture', '-qDEB_HOST_MULTIARCH'], text=True).strip()}/{('fcitx5' if framework == 'fcitx5' else 'fcitx')}/{filename}"
        )
        addon.parent.mkdir(parents=True)
        shutil.copy2(library, addon)
        addon.chmod(0o644)
        metadata_name = (
            "fcitx5/addon/openasrinput.conf"
            if framework == "fcitx5"
            else "fcitx/addon/fcitx-openasrinput.conf"
        )
        metadata = stage / "usr/share" / metadata_name
        metadata.parent.mkdir(parents=True)
        content = (
            (
                ROOT
                / "src/native"
                / framework
                / ("openasrinput.conf" if framework == "fcitx5" else "fcitx-openasrinput.conf")
            )
            .read_text()
            .replace("Enabled=False", "Enabled=True")
        )
        metadata.write_text(content)
        if framework == "fcitx5":
            package_extensions(stage / "usr/share/gnome-shell/extensions")
        desktop = stage / "usr/share/applications/openasrinput.desktop"
        desktop.parent.mkdir(parents=True)
        desktop.write_text(
            "[Desktop Entry]\nType=Application\nName=OpenASRInput 设置\nExec=/usr/bin/openasrinput settings\nIcon=openasrinput\nTerminal=false\nCategories=Utility;Accessibility;\n"
        )
        icon = stage / "usr/share/icons/hicolor/scalable/apps/openasrinput.svg"
        icon.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "src/openasrinput/presentation/branding/logo.svg", icon)
        # Registered at install time; per-user activation writes the socket config.
        units = stage / "usr/lib/systemd/user"
        units.mkdir(parents=True)
        for name, command in (
            ("openasrinput.service", "run-daemon"),
            ("openasrinput-settings.service", "settings-server --no-open"),
        ):
            (units / name).write_text(
                "[Unit]\nDescription=OpenASRInput user application\n"
                "After=graphical-session.target\nPartOf=graphical-session.target\n"
                "[Service]\nType=simple\nExecStart=/usr/bin/openasrinput " + command + "\n"
                "Restart=on-failure\nRestartSec=3\n"
                "[Install]\nWantedBy=graphical-session.target\n"
            )
        activate = stage / "usr/share/applications/openasrinput-start.desktop"
        activate.write_text(
            "[Desktop Entry]\nType=Application\nName=OpenASRInput 启用语音输入\n"
            "Exec=/usr/bin/openasrinput start\nIcon=openasrinput\n"
            "Terminal=false\nCategories=Utility;Accessibility;\n"
        )
        docs = stage / "usr/share/doc/openasrinput"
        docs.mkdir(parents=True)
        shutil.copy2(ROOT / "README.md", docs / "README.md")
        shutil.copy2(ROOT / "README.zh-CN.md", docs / "README.zh-CN.md")
        shutil.copy2(ROOT / "LICENSE", docs / "LICENSE")
        shutil.copy2(ROOT / "LICENSE", docs / "copyright")
        shutil.copytree(ROOT / "docs", docs / "docs", ignore=shutil.ignore_patterns("history"))
        (docs / "tests/functional").mkdir(parents=True)
        shutil.copy2(
            ROOT / "tests/functional/manifest.json", docs / "tests/functional/manifest.json"
        )
        control = stage / "DEBIAN"
        control.mkdir()
        source_metadata = stage / "debian"
        source_metadata.mkdir()
        (source_metadata / "control").write_text(
            "Source: openasrinput\nSection: utils\nPriority: optional\nMaintainer: OpenASRInput maintainers\n\n"
            "Package: openasrinput\nArchitecture: any\nDescription: Cursor dictation\n"
        )
        private_depends = []
        private_objects = []
        if runtime_dir:
            # ICU changes its SONAME across Ubuntu/Debian releases. Keep these
            # versioned libraries private; do not require e.g. libicu70 on Debian 12.
            linkage = subprocess.check_output(["ldd", str(addon)], text=True)
            private = addon.parent / "openasrinput-libs"
            private.mkdir()
            shlibs = []
            for line in linkage.splitlines():
                parts = line.split()
                if len(parts) < 3 or not parts[0].startswith("libicu") or parts[1] != "=>":
                    continue
                source = Path(parts[2])
                shutil.copy2(source.resolve(), private / parts[0])
                private_objects.append("-e" + str(private / parts[0]))
                subprocess.run(
                    ["patchelf", "--set-rpath", "$ORIGIN", str(private / parts[0])], check=True
                )
                name, version = parts[0].split(".so.")
                shlibs.append(f"{name} {version} openasrinput\n")
            (source_metadata / "shlibs.local").write_text("".join(shlibs))
            subprocess.run(
                ["patchelf", "--set-rpath", "$ORIGIN/openasrinput-libs", str(addon)], check=True
            )
            private_depends = ["-xopenasrinput", "-l" + str(private)]
        dependencies = subprocess.check_output(
            ["dpkg-shlibdeps", "-O", *private_depends, "-e" + str(addon), *private_objects],
            cwd=stage,
            text=True,
        )
        native_depends = next(
            line.split("=", 1)[1]
            for line in dependencies.splitlines()
            if line.startswith("shlibs:Depends=")
        )
        shutil.rmtree(source_metadata)
        framework_depends = (
            "fcitx5 (>= 5.0.14)"
            if framework == "fcitx5"
            else "fcitx-bin (>= 1:4.2.9.8), fcitx-modules, fcitx-module-x11"
        )
        python_depends = (
            "libc6 (>= 2.35), ca-certificates, "
            if runtime_dir
            else "python3 (>= 3.10), python3-aiohttp (>= 3.12), "
        )
        (control / "control").write_text(
            f"Package: openasrinput\nVersion: {VERSION}\nArchitecture: {architecture}\n"
            "Maintainer: OpenASRInput maintainers\nSection: utils\nPriority: optional\n"
            "Depends: "
            + python_depends
            + framework_depends
            + ", "
            + native_depends
            + ", libxrandr2, pulseaudio-utils\n"
            "Recommends: xdg-utils\n"
            f"Description: Independent cursor dictation with Portal ASR and {framework}\n"
            " Native exclusive dictation, editable preview, waveform and local settings.\n"
            " Configure a remote or local OpenASRPortal and its dedicated ASR access key.\n"
        )
        package = output / f"openasrinput_{VERSION}_{architecture}.deb"
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(stage), str(package)], check=True
        )
    print(
        json.dumps(
            {
                "package": str(package),
                "architecture": architecture,
                "framework": framework,
                "runtime": "private Python runtime" if runtime_dir else "system Python",
            },
            ensure_ascii=False,
        )
    )
    return package


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--framework", choices=("auto", "fcitx4", "fcitx5"), default="auto")
    parser.add_argument(
        "--native-build", type=Path, help="native build directory from the target distribution"
    )
    parser.add_argument(
        "--runtime-dir", type=Path, help="frozen runtime from scripts/build_runtime.py"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    output = args.output or ROOT / ".cache/build/artifacts/linux" / architecture / args.framework
    build(
        output.resolve(),
        args.framework,
        args.native_build.resolve() if args.native_build else None,
        args.runtime_dir.resolve() if args.runtime_dir else None,
    )
