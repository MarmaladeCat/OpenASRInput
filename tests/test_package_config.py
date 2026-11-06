"""Exercise the Linux package entrypoint with isolated installed and legacy roots."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.name == "nt", "Linux package entrypoint")
class PackageConfigurationTests(unittest.TestCase):
    def test_launcher_uses_installed_root_and_migrates_unless_explicitly_overridden(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        for explicit, migrate in ((False, False), (False, True), (True, True)):
            with self.subTest(explicit=explicit, migrate=migrate), tempfile.TemporaryDirectory(
                dir=ROOT / "test-results", prefix="package-config-"
            ) as directory:
                base = Path(directory)
                legacy = base / "home/.config/openasrinput"
                legacy.mkdir(parents=True)
                original = '{"overlay":{"theme":"nord"}}'
                if migrate:
                    (legacy / "input.json").write_text(original)
                    (legacy / "input.models.json").write_text('{"fixture":true}')
                handoff = base / "handoff.json"
                handoff.write_text(json.dumps({
                    "schemaVersion": 1,
                    "generation": "package-config-regression",
                    "portal": {
                        "id": "local-input", "name": "Local test Portal",
                        "url": "http://127.0.0.1:19876", "apiKey": "fixture-only-key",
                        "profileId": "",
                    },
                }))
                env = {
                    key: value for key, value in os.environ.items()
                    if not key.startswith("OPENASR")
                }
                env.update(
                    HOME=str(base / "home"), XDG_CONFIG_HOME=str(legacy.parent),
                    OPENASR_DATA_ROOT=str(base / "shared"),
                    OPENASRINPUT_APP_ROOT=str(ROOT / "src"),
                    PYTHONDONTWRITEBYTECODE="1",
                )
                installed = base / "shared/input" / str(os.getuid()) / "input.json"
                expected = base / "explicit.json" if explicit else installed
                if explicit:
                    env["OPENASRINPUT_CONFIG"] = str(expected)
                subprocess.run(
                    [sys.executable, str(ROOT / "packaging/openasrinput"),
                     "provision", "--handoff", str(handoff)],
                    env=env, cwd=base, check=True, capture_output=True, text=True,
                )
                value = json.loads(expected.read_text())
                self.assertEqual(value["portal"]["activePortalCardId"], "local-input")
                self.assertEqual(value["portal"]["apiKey"], "fixture-only-key")
                if migrate:
                    self.assertEqual((legacy / "input.json").read_text(), original)
                else:
                    self.assertFalse((legacy / "input.json").exists())
                self.assertEqual(expected.stat().st_mode & 0o777, 0o600)
                if explicit:
                    self.assertFalse(installed.exists())
                    self.assertEqual(value["overlay"]["theme"], "material")
                else:
                    self.assertEqual(value["overlay"]["theme"], "nord" if migrate else "material")
                    self.assertEqual(expected.parent.stat().st_mode & 0o777, 0o700)
                    if migrate:
                        self.assertEqual(expected.with_suffix(".models.json").read_text(), '{"fixture":true}')


if __name__ == "__main__":
    unittest.main()
