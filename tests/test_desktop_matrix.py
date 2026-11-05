"""Scope exclusions must never hide real failures or rewrite historic evidence."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
with patch.object(sys, "path", [str(ROOT / "scripts"), *sys.path]):
    spec = importlib.util.spec_from_file_location(
        "desktop_matrix", ROOT / "scripts/desktop_matrix.py"
    )
    matrix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(matrix)


class DesktopMatrixTests(unittest.TestCase):
    def args(self, root, **overrides):
        return SimpleNamespace(
            **{
                "profile": "desktop-v4",
                "releases": ["kali"],
                "arches": ["amd64"],
                "desktops": ["kde"],
                "protocols": ["x11"],
                "frameworks": ["fcitx4"],
                "package_root": root / "packages",
                "probe_root": root / "probes",
                "minimum_free_gib": 0,
                "skip_images": True,
                "build_only": False,
                "network": "none",
                "resume": False,
                **overrides,
            }
        )

    def test_versioned_scope_keeps_legacy_and_only_excludes_requested_intersections(self):
        for profile, count in (("desktop-v1", 108), ("desktop-v2", 216)):
            manifest = matrix.scope(profile)
            self.assertEqual(len(manifest["targets"]), count)
            self.assertEqual(manifest["excluded"], [])
        current = matrix.scope()

        def keys(rows):
            return {
                tuple(
                    row[name]
                    for name in ("release", "architecture", "desktop", "protocol", "framework")
                )
                for row in rows
            }

        targets, excluded = keys(current["targets"]), keys(current["excluded"])
        self.assertEqual((len(targets), len(excluded)), (134, 46))
        self.assertFalse(targets & excluded)
        self.assertEqual(
            targets | excluded,
            keys(row for row in matrix.scope("desktop-v2")["targets"] if row["release"] != "20.04"),
        )
        self.assertFalse(any(row[0] == "20.04" for row in targets | excluded))
        self.assertIn(("26.04", "arm64", "xfce", "wayland", "ibus"), targets)
        self.assertIn(("kali", "arm64", "kde", "x11", "fcitx5"), targets)
        self.assertEqual(len(matrix.exclusions("desktop-v4", "kali", "gnome", "x11", "fcitx4")), 2)
        historic = matrix.scope("desktop-v3")
        self.assertEqual((len(historic["targets"]), len(historic["excluded"])), (164, 52))
        self.assertIn(("20.04", "amd64", "kde", "x11", "fcitx4"), keys(historic["targets"]))

    def test_excluded_only_selection_needs_no_package_image_or_test(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            root = Path(directory)
            with (
                patch.object(matrix, "RESULTS", root),
                patch.object(matrix, "invoke") as invoke,
                patch.object(matrix, "build_images") as build,
                patch.object(matrix.subprocess, "check_output") as inspect,
            ):
                matrix.run_matrix(self.args(root, skip_images=False), ROOT, "test")
            invoke.assert_not_called()
            build.assert_not_called()
            inspect.assert_not_called()
            self.assertFalse((root / "kali-amd64-kde-x11-fcitx4").exists())
            self.assertEqual(len(json.loads((root / "summary.json").read_text())), 134)
            self.assertEqual(len(json.loads((root / "scope.json").read_text())["excluded"]), 46)

    def test_kali_images_skip_unavailable_fcitx4_but_build_other_frameworks(self):
        with patch.object(matrix, "invoke") as invoke:
            matrix.build_images(
                "kali", "amd64", self.args(ROOT, frameworks=["ibus", "fcitx4", "fcitx5"])
            )
        commands = [call.args[0] for call in invoke.call_args_list]
        self.assertEqual(len(commands), 2)
        self.assertIn("FRAMEWORK=ibus", commands[0])
        self.assertIn("FRAMEWORK=fcitx5", commands[1])

    def test_included_package_incompatibility_still_fails(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            root = Path(directory)
            package = root / "packages/amd64/auto/candidate.deb"
            package.parent.mkdir(parents=True)
            package.write_bytes(b"candidate")
            with (
                patch.object(matrix, "RESULTS", root),
                patch.object(matrix, "invoke"),
                patch.object(matrix, "source_fingerprint", return_value="test"),
            ):
                with self.assertRaises(SystemExit) as failure:
                    matrix.run_matrix(
                        self.args(root, releases=["20.04"], profile="desktop-v3"), ROOT, "test"
                    )
            self.assertEqual(failure.exception.code, 1)
            record = json.loads((root / "20.04-amd64-kde-x11-fcitx4/result.json").read_text())
            self.assertEqual(record["status"], "package-unsupported")

    def test_included_execution_failure_is_retained_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            root = Path(directory)
            package = root / "packages/amd64/auto/candidate.deb"
            package.parent.mkdir(parents=True)
            package.write_bytes(b"candidate")
            with (
                patch.object(matrix, "RESULTS", root),
                patch.object(
                    matrix, "invoke", side_effect=subprocess.CalledProcessError(1, "test")
                ),
                patch.object(matrix.subprocess, "check_output", return_value="image-id"),
                patch.object(matrix.subprocess, "run"),
                patch.object(matrix, "source_fingerprint", return_value="test"),
            ):
                with self.assertRaises(SystemExit) as failure:
                    matrix.run_matrix(self.args(root, frameworks=["fcitx5"]), ROOT, "test")
            self.assertEqual(failure.exception.code, 1)
            rows = json.loads((root / "summary.json").read_text())
            self.assertEqual(sum(row["status"] == "failed" for row in rows), 1)

    def test_summary_does_not_reinterpret_old_profile(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            root = Path(directory)
            original = '[{"profile": "desktop-v2", "status": "failed"}]\n'
            (root / "summary.json").write_text(original)
            with patch.object(matrix, "RESULTS", root):
                with self.assertRaisesRegex(ValueError, "use a new directory"):
                    matrix.summarize()
            self.assertEqual((root / "summary.json").read_text(), original)
            self.assertFalse((root / "scope.json").exists())


if __name__ == "__main__":
    unittest.main()
