"""The series launcher can validate a connection using only a public product entry."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openasrinput.infrastructure.config import ROOT


class ConnectionCliTests(unittest.TestCase):
    def test_fresh_config_and_explicit_key_without_native_bridge(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            config = Path(directory) / "input.json"
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
            env.pop("OPENASRINPUT_PORTAL_KEY", None)
            command = [
                sys.executable,
                # Preflight is stdlib-only, even without the optional network dependencies.
                "-S",
                "-m",
                "openasrinput",
                "check-config",
                "--config",
                str(config),
                "--portal-url",
                "http://127.0.0.1:19000",
                "--profile",
                "explicit",
            ]
            missing = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("尚未配置当前 Portal", missing.stderr)
            self.assertFalse(config.exists())
            env["OPENASRINPUT_PORTAL_KEY"] = "private-explicit-key"
            ready = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(ready.returncode, 0, ready.stderr)
            self.assertEqual(
                json.loads(ready.stdout),
                {
                    "configured": True,
                    "portalUrl": "http://127.0.0.1:19000",
                    "profileId": "explicit",
                },
            )
            self.assertNotIn("private-explicit-key", ready.stdout + ready.stderr)
            self.assertFalse(config.exists())
