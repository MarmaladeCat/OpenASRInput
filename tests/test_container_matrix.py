import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "container_matrix", ROOT / "scripts/container_matrix.py"
)
matrix = importlib.util.module_from_spec(spec)
spec.loader.exec_module(matrix)


class ContainerMatrixTests(unittest.TestCase):
    def test_build_snapshot_survives_later_edits_and_is_cleaned(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            root = Path(directory)
            (root / "source.py").write_text("original")
            (root / "private.json").write_text("not inventoried")
            with (
                patch.object(matrix, "ROOT", root),
                patch.object(matrix, "source_paths", return_value=[b"source.py"]),
            ):
                before = matrix.source_fingerprint()
                with matrix.source_snapshot(root) as (snapshot, fingerprint):
                    (root / "source.py").write_text("edited during build")
                    self.assertEqual(fingerprint, before)
                    self.assertEqual((snapshot / "source.py").read_text(), "original")
                    self.assertFalse((snapshot / "private.json").exists())
                self.assertFalse(snapshot.exists())

    def test_mounts_keep_source_read_only_and_isolate_architectures(self):
        amd = matrix.mounts("ubuntu22", "amd64")
        arm = matrix.mounts("ubuntu22", "arm64")
        self.assertEqual(amd[ROOT], ("/source", "ro"))
        self.assertEqual(set(amd).intersection(arm), {ROOT})
        self.assertIn(ROOT / "build/matrix/ubuntu22/arm64", arm)
        self.assertNotIn(Path.home(), amd)
        self.assertNotIn(Path("/var/run/docker.sock"), amd)

    def test_wrong_execution_architecture_fails_before_build(self):
        with (
            patch.dict(os.environ, EXPECTED_ARCH="arm64"),
            patch.object(matrix.platform, "machine", return_value="x86_64"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Wrong CPU"):
                matrix.inside(SimpleNamespace())

    def test_failed_command_retains_evidence_and_cannot_pass(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            log = Path(directory) / "failed.log"
            with self.assertRaisesRegex(RuntimeError, "Exit 7"):
                matrix.run(
                    [sys.executable, "-c", "print('failure evidence'); raise SystemExit(7)"], log
                )
            self.assertIn("failure evidence", log.read_text())
