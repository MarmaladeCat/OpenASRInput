"""Cache hits must survive doc edits, but never source/toolchain/payload changes."""

import importlib.util
import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("runtime_cache", ROOT / "scripts/runtime_cache.py")
cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cache)


class RuntimeCacheTests(unittest.TestCase):
    def test_wheels_reuse_offline_and_refetch_only_changed_or_damaged_sets(self):
        wheels = runpy.run_path(str(ROOT / "scripts/wheel_cache.py"))
        def download(command, **kwargs):
            destination = Path(command[command.index("--dest") + 1])
            (destination / "fixture-1-py3-none-any.whl").write_bytes(b"wheel fixture")
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            with patch.object(wheels["subprocess"], "run", side_effect=download) as run:
                target = wheels["wheelhouse"](Path(directory), ["fixture==1"], "3.12")
                self.assertEqual(run.call_count, 1)
                self.assertEqual(wheels["wheelhouse"](Path(directory), ["fixture==1"], "3.12"), target)
                self.assertEqual(run.call_count, 1)
                next(target.glob("*.whl")).write_bytes(b"corrupt")
                wheels["wheelhouse"](Path(directory), ["fixture==1"], "3.12")
                self.assertEqual(run.call_count, 2)
                other = wheels["wheelhouse"](Path(directory), ["fixture==1"], "3.13")
                self.assertNotEqual(other, target)
                self.assertEqual(run.call_count, 3)

    def test_content_identity_and_payload_integrity(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            root = Path(directory)
            (root / "src").mkdir()
            source = root / "src/app.py"
            source.write_text("first")
            output = root / "runtime"
            output.mkdir()
            binary = output / "app"
            binary.write_bytes(b"frozen runtime")
            marker = root / "runtime-cache.json"
            with patch.dict(os.environ, {"OPENASR_BUILD_IMAGE": "sha256:toolchain-a"}):
                key = cache.fingerprint(root)
                self.assertFalse(cache.reusable(marker, key, output))
                cache.record(marker, key, output)
                self.assertTrue(cache.reusable(marker, key, output))
                (root / "README.md").write_text("New documentation")
                self.assertEqual(cache.fingerprint(root), key)
                old = source.stat()
                source.write_text("other")
                os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns))
                self.assertNotEqual(cache.fingerprint(root), key)
                source.write_text("first")
                binary.write_bytes(b"tampered runtime")
                self.assertFalse(cache.reusable(marker, key, output))
                binary.write_bytes(b"frozen runtime")
                (output / "unexpected").write_bytes(b"extra")
                self.assertFalse(cache.reusable(marker, key, output))
                (output / "unexpected").unlink()
                self.assertTrue(cache.reusable(marker, key, output))
                os.environ["OPENASR_BUILD_IMAGE"] = "sha256:toolchain-b"
                self.assertNotEqual(cache.fingerprint(root), key)
                del os.environ["OPENASR_BUILD_IMAGE"]
                self.assertIsNone(cache.fingerprint(root))
                self.assertFalse(cache.reusable(marker, None, output))
