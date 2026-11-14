import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from openasrinput.entrypoints.cli import main


class SettingsCliTests(unittest.TestCase):
    def test_settings_default_is_fixed_and_does_not_open_browser_when_requested(self):
        serve = AsyncMock()
        with (
            tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "test-results") as temporary,
            patch.dict(os.environ, {"OPENASRINPUT_CONFIG": str(Path(temporary) / "input.json")}, clear=True),
            patch("sys.argv", ["openasrinput", "settings", "--no-open"]),
            patch("openasrinput.presentation.settings_server.serve", serve),
        ):
            main()
        self.assertEqual(serve.await_args.kwargs["port"], 10088)
        self.assertFalse(serve.await_args.kwargs["open_window"])
