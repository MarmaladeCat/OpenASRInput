import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openasrinput.domain.audio_processing import AudioProcessor
from openasrinput.infrastructure.config import (
    ROOT,
    ConfigConflict,
    ConfigStore,
    atomic_json,
    default_path,
    normalize,
)
from openasrinput.infrastructure.platform_support import config_home


class ConfigTests(unittest.TestCase):
    def test_panel_preferences_and_independent_settings_theme(self):
        old = normalize({"overlay": {"theme": "nord", "colorMode": "dark"}})
        self.assertEqual(old["settings"], {"theme": "nord", "colorMode": "dark"})
        atomic_json(self.store.path, old)
        updated = self.store.patched(
            {
                "overlay": {"position": "top-right", "transparency": 35, "theme": "github"},
                "settings": {"theme": "material", "colorMode": "light"},
            }
        )
        atomic_json(self.store.path, updated)
        public = self.store.public()["config"]
        self.assertEqual(public["overlay"]["transparency"], 35)
        self.assertEqual(public["overlay"]["position"], "top-right")
        self.assertEqual(public["settings"]["theme"], "material")
        self.assertEqual(public["overlay"]["theme"], "github")
        for bad in (-1, 101, 0.5, True, "30"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.store.patched({"overlay": {"transparency": bad}})
        with self.assertRaises(ValueError):
            self.store.patched({"overlay": {"position": "invalid"}})

    def test_text_model_secret_is_redacted_preserved_and_explicitly_clearable(self):
        config = self.store.patched({"textEdit": {"apiKey": "private-text-key"}})
        atomic_json(self.store.path, config)
        self.assertNotIn("private-text-key", json.dumps(self.store.public()))
        self.assertTrue(self.store.public()["config"]["textEdit"]["hasApiKey"])
        self.assertEqual(
            self.store.patched({"textEdit": {"apiKey": ""}})["textEdit"]["apiKey"],
            "private-text-key",
        )
        self.assertEqual(
            self.store.patched({"textEdit": {"clearApiKey": True}})["textEdit"]["apiKey"], ""
        )

    def test_windows_atomic_replace_retries_transient_reader_lock(self):
        error = PermissionError("reader denies delete sharing")
        error.winerror = 32
        replace = os.replace
        attempts = []

        def replace_after_lock(source, destination):
            attempts.append((source, destination))
            if len(attempts) == 1:
                raise error
            replace(source, destination)

        with (
            patch("openasrinput.infrastructure.config.sys.platform", "win32"),
            patch("openasrinput.infrastructure.config.os.replace", side_effect=replace_after_lock),
            patch("openasrinput.infrastructure.config.time.sleep") as sleep,
        ):
            atomic_json(self.store.path, {"new": "中文"})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0], attempts[1])
        sleep.assert_called_once_with(0.01)
        self.assertEqual(list(self.store.path.parent.glob(".input.json*")), [])
        self.assertEqual(json.loads(self.store.path.read_text(encoding="utf-8")), {"new": "中文"})

    def test_windows_persistent_lock_preserves_existing_json_and_cleans_temporary(self):
        self.store.path.write_text('{"old": 1}')
        error = PermissionError("locked")
        error.winerror = 5
        with (
            patch("openasrinput.infrastructure.config.sys.platform", "win32"),
            patch("openasrinput.infrastructure.config.os.replace", side_effect=error) as move,
            patch("openasrinput.infrastructure.config.time.sleep"),
        ):
            with self.assertRaises(PermissionError):
                atomic_json(self.store.path, {"new": 2})
        self.assertEqual(move.call_count, 8)
        self.assertEqual(self.store.path.read_text(), '{"old": 1}')
        self.assertEqual(list(self.store.path.parent.glob(".input.json*")), [])

    def test_explicit_paths_do_not_require_home_environment(self):
        explicit = self.store.path
        with patch.dict(os.environ, {"OPENASRINPUT_CONFIG": str(explicit)}, clear=True):
            with patch("openasrinput.infrastructure.config.config_home", side_effect=RuntimeError):
                self.assertEqual(default_path(), explicit)
        variable = "APPDATA" if os.name == "nt" else "XDG_CONFIG_HOME"
        product = "OpenASRInput" if os.name == "nt" else "openasrinput"
        with patch.dict(os.environ, {variable: str(explicit.parent)}, clear=True):
            with patch("pathlib.Path.home", side_effect=RuntimeError):
                self.assertEqual(config_home(), explicit.parent / product)

    def test_installed_user_migration_preserves_credentials_and_metadata_once(self):
        root = Path(self.directory.name)
        legacy = root / "legacy"
        legacy.mkdir()
        value = {
            "portal": {"url": "http://127.0.0.1:10087", "apiKey": "migration-fixture-key"},
            "custom": {"name": "中文"},
        }
        raw = json.dumps(value, ensure_ascii=False).encode()
        (legacy / "input.json").write_bytes(raw)
        (legacy / "input.models.json").write_text('{"saved":true}')
        (legacy / "input.runtime.json").write_text('{"running":true}')
        with (
            patch.dict(os.environ, {"OPENASR_DATA_ROOT": str(root / "shared")}, clear=True),
            patch("openasrinput.infrastructure.config.legacy_config_home", return_value=legacy),
        ):
            store = ConfigStore()
            self.assertEqual(store.path.read_bytes(), raw)
            self.assertEqual(store.path.with_suffix(".models.json").read_text(), '{"saved":true}')
            self.assertFalse(store.status_path.exists())
            self.assertEqual((legacy / "input.json").read_bytes(), raw)
            store.path.write_text('{"new":true}')
            self.assertEqual(ConfigStore().path.read_text(), '{"new":true}')
            explicit = ConfigStore(root / "explicit.json")
            self.assertFalse(explicit.path.exists())
            if os.name != "nt":
                self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(store.path.parent.stat().st_mode & 0o777, 0o700)

    @unittest.skipIf(os.name == "nt", "POSIX symlink ownership")
    def test_installed_directory_refuses_user_symlink(self):
        root = Path(self.directory.name)
        shared = root / "shared/input"
        shared.mkdir(parents=True)
        (shared / str(os.getuid())).symlink_to(root, target_is_directory=True)
        with patch.dict(os.environ, {"OPENASR_DATA_ROOT": str(root / "shared")}, clear=True):
            with self.assertRaises(PermissionError):
                config_home()

    def test_stale_status_preserves_exit_diagnostics_without_claiming_running(self):
        self.store.status_path.write_text(
            json.dumps(
                {
                    "running": True,
                    "state": "failed",
                    "updatedAt": 0,
                    "stopReason": "error",
                    "error": "microphone unavailable",
                }
            )
        )
        status = self.store.status()
        self.assertFalse(status["running"])
        self.assertEqual(status["state"], "stopped")
        self.assertEqual(status["error"], "microphone unavailable")
        self.assertEqual(status["stopReason"], "error")

    def setUp(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="config-", dir=ROOT / "test-results")
        self.store = ConfigStore(Path(self.directory.name) / "input.json")

    def tearDown(self):
        self.directory.cleanup()

    def save(self, patch):
        return self.store.save(patch, self.store.read()[1])

    def test_missing_file_does_not_create_or_connect_anything(self):
        public = self.store.public()
        self.assertEqual(public["revision"], "defaults")
        self.assertFalse(public["config"]["portal"]["hasApiKey"])
        self.assertFalse(self.store.path.exists())

    def test_installed_portal_defaults_do_not_override_saved_user_configuration(self):
        connection = Path(self.directory.name) / "portal.json"
        connection.write_text(json.dumps({"url": "http://127.0.0.1:10087", "apiKey": "local-test"}))
        self.store = ConfigStore(self.store.path, system_portal=connection)
        self.assertEqual(self.store.read()[0]["portal"]["apiKey"], "local-test")
        self.save({"portal": {"url": "https://asr.example.org", "apiKey": "remote-test"}})
        connection.write_text(json.dumps({"url": "http://127.0.0.1:10087", "apiKey": "new-local"}))
        self.assertEqual(self.store.read()[0]["portal"]["apiKey"], "remote-test")

    def test_secret_retention_redaction_and_explicit_clear(self):
        self.save({"portal": {"apiKey": "private-test-key"}})
        self.save({"portal": {"apiKey": "", "url": "http://localhost:1234"}})
        self.assertEqual(self.store.read()[0]["portal"]["apiKey"], "private-test-key")
        self.assertNotIn("private-test-key", json.dumps(self.store.public()))
        if os.name != "nt":  # Windows uses the user's directory ACL, not POSIX mode bits.
            self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)
        self.save({"portal": {"clearApiKey": True}})
        self.assertFalse(self.store.public()["config"]["portal"]["hasApiKey"])

    def test_stale_window_cannot_overwrite_newer_settings(self):
        original_revision = self.store.read()[1]
        self.save({"overlay": {"theme": "nord"}})
        with self.assertRaises(ConfigConflict):
            self.store.save({"overlay": {"theme": "github"}}, original_revision)
        self.assertEqual(self.store.read()[0]["overlay"]["theme"], "nord")

    def test_invalid_input_preserves_file_and_unknown_extensions_survive(self):
        self.store.path.write_text(
            json.dumps({"custom": {"keep": 42}, "portal": {"apiKey": "test-key"}})
        )
        self.save({"overlay": {"colorMode": "dark"}})
        self.assertEqual(self.store.read()[0]["custom"], {"keep": 42})
        self.assertNotIn("custom", self.store.public()["config"])
        raw = self.store.path.read_bytes()
        for invalid_patch in (
            {"overlay": {"scale": True}},
            {"overlay": {"theme": []}},
            {"portal": {"url": "http://user:secret@localhost"}},
            {"portal": {"url": "http://localhost:99999"}},
            {"overlay": {"width": 200}},
            {"audio": {"gain": 10}},
            {"unsupported": {}},
        ):
            with self.subTest(patch=invalid_patch), self.assertRaises(ValueError):
                self.save(invalid_patch)
            self.assertEqual(self.store.path.read_bytes(), raw)

    def test_corrupted_config_is_not_overwritten(self):
        self.store.path.write_text("{broken")
        with self.assertRaises(ValueError):
            self.store.read()
        self.assertEqual(self.store.path.read_text(), "{broken")

    def test_fixed_audio_and_word_buffer_contract(self):
        for config in ({"audio": {"sampleRate": 48000}}, {"overlay": {"previewBufferWords": 30}}):
            with self.assertRaises(ValueError):
                normalize(config)

    def test_default_profile_can_be_selected_without_losing_explicit_settings(self):
        self.assertEqual(normalize({})["portal"]["profileId"], "")
        self.save({"portal": {"profileId": "cloud"}})
        self.assertEqual(self.store.read()[0]["portal"]["profileId"], "cloud")
        self.save({"portal": {"profileId": ""}})
        self.assertEqual(self.store.read()[0]["portal"]["profileId"], "")
        self.assertEqual(normalize({"portal": {"profileId": None}})["portal"]["profileId"], "")

    def test_actual_pcm_gain_and_saturation(self):
        import struct

        pcm = struct.pack("<4h", 12000, -12000, 20000, -20000)
        self.assertEqual(
            struct.unpack("<4h", AudioProcessor(2).process(pcm)), (24000, -24000, 32767, -32768)
        )
        self.assertEqual(AudioProcessor(1).process(pcm), pcm)
