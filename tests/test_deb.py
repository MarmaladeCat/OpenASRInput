"""Unpack/configure/remove deb in a private dpkg root; never install on the host."""

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(
    1
)


def main():
    architecture = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        type=Path,
        default=ROOT / f".cache/build/artifacts/linux/{architecture}/auto/openasrinput_{VERSION}_{architecture}.deb",
    )
    package = parser.parse_args().package
    (ROOT / "test-results").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deb-check-", dir=ROOT / "test-results") as directory:
        stage = Path(directory)
        subprocess.run(["dpkg-deb", "-x", str(package), str(stage)], check=True)
        source = stage / "usr/lib/openasrinput/openasrinput"
        if not source.exists():
            source = stage / "usr/lib/openasrinput/runtime/_internal/openasrinput"
        assert (source / "presentation/web/index.html").exists()
        assert (source / "presentation/branding/logo.svg").is_file()
        assert (stage / "usr/share/icons/hicolor/scalable/apps/openasrinput.svg").is_file()
        extension = stage / "usr/share/gnome-shell/extensions/openasrinput@local"
        framework = (stage / "usr/lib/openasrinput/framework").read_text().strip()
        assert framework in ("auto", "fcitx4", "fcitx5")
        if framework == "auto":
            assert (stage / "usr/lib/openasrinput/ibus/engine.py").is_file()
            assert (stage / "usr/lib/openasrinput/ibus/voice-panel").is_file()
            assert (stage / "usr/share/ibus/component/openasrinput.xml").is_file()
            assert list(stage.glob("usr/lib/*/fcitx/fcitx-openasrinput.so"))
            assert list(stage.glob("usr/lib/*/fcitx5/libopenasrinput.so"))
            depends = subprocess.check_output(
                ["dpkg-deb", "-f", str(package), "Depends"], text=True
            )
            assert not any(
                item.strip().startswith(("fcitx", "libfcitx")) for item in depends.split(",")
            )
        if framework in ("auto", "fcitx5"):
            assert (extension / "metadata.json").exists()
            assert (extension / "extension.js").exists()
            assert (extension / "panel.mjs").exists()
        else:
            assert not extension.exists(), "Fcitx4 uses its own X11 panel"
        assert not list(stage.rglob("*.db"))
        assert not list(stage.rglob("*.env"))
        assert not (stage / "home").exists()
        env = {
            **os.environ,
            "OPENASRINPUT_APP_ROOT": str(stage / "usr/lib/openasrinput"),
            "OPENASRINPUT_CONFIG": str(stage / "home/config/input.json"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        launcher = stage / "usr/bin/openasrinput"
        result = subprocess.check_output([str(launcher), "--version"], env=env, text=True)
        assert VERSION in result
        subprocess.run([str(launcher), "demo"], env=env, check=True)
        # Actual package-manager operations, redirected into an isolated filesystem.
        dpkg_root = stage / "dpkg-root"
        dpkg_root.mkdir()
        database = dpkg_root / "var/lib/dpkg"
        database.mkdir(parents=True)
        required = subprocess.check_output(["dpkg-deb", "-f", str(package), "Depends"], text=True)
        names = [dependency.strip().split()[0] for dependency in required.strip().split(",")]
        installed = subprocess.check_output(
            [
                "dpkg-query",
                "-W",
                "-f",
                "Package: ${Package}\nStatus: ${Status}\nArchitecture: ${Architecture}\nVersion: ${Version}\nProvides: ${Provides}\nMulti-Arch: ${Multi-Arch}\nMaintainer: ${Maintainer}\nDescription: runtime dependency\n\n",
            ],
            text=True,
        )
        # Newer Debian/Ubuntu t64 packages provide the old package names.
        # Preserve real Provides/version metadata rather than inventing a fake
        # installed record for a virtual package with an empty Version field.
        records, packages = [], []
        for record in installed.split("\n\n"):
            fields = dict(line.split(": ", 1) for line in record.splitlines() if ": " in line)
            provided = {
                item.strip().split()[0]
                for item in fields.get("Provides", "").split(",")
                if item.strip()
            }
            if fields.get("Status") != "install ok installed" or not fields.get("Version"):
                continue
            if fields.get("Architecture") not in (architecture, "all"):
                continue
            if fields["Package"] in names or provided.intersection(names):
                records.append(
                    "\n".join(line for line in record.splitlines() if line.split(": ", 1)[-1])
                )
                packages.append(fields["Package"])
        (database / "status").write_text("\n\n".join(records) + "\n\n")
        (database / "info").mkdir()
        for name in packages:
            (database / "info" / (name + ".list")).write_text("")
        config = stage / "dpkg-config"
        config.mkdir()
        # Hide host dpkg hooks and keep every host path read-only. The only
        # writable filesystem is the redirected package-manager root.
        sandbox = [
            "bwrap",
            "--unshare-user",
            "--uid",
            "0",
            "--gid",
            "0",
            "--ro-bind",
            "/",
            "/",
            "--bind",
            str(dpkg_root),
            str(dpkg_root),
            "--ro-bind",
            str(config),
            "/etc/dpkg",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--die-with-parent",
        ]
        dpkg = sandbox + [
            "dpkg",
            "--force-not-root",
            "--root=" + str(dpkg_root),
            "--log=" + str(dpkg_root / "dpkg.log"),
        ]
        subprocess.run(dpkg + ["--unpack", str(package)], check=True)
        subprocess.run(dpkg + ["--configure", "openasrinput"], check=True)
        user_config = dpkg_root / "home/test/.config/openasrinput/input.json"
        user_config.parent.mkdir(parents=True)
        user_config.write_text('{"keep":"user-settings"}')
        subprocess.run(dpkg + ["--remove", "openasrinput"], check=True)
        assert user_config.read_text() == '{"keep":"user-settings"}'
        assert not (dpkg_root / "usr/bin/openasrinput").exists()
        print(
            "PASS deb: clean payload, standalone launcher, isolated dpkg install/remove, user config preserved"
        )


if __name__ == "__main__":
    main()
