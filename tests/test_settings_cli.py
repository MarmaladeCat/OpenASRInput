import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from openasrinput.entrypoints.cli import main


class SettingsCliTests(unittest.TestCase):
    def test_settings_default_is_fixed_and_does_not_open_browser_when_requested(self):
        serve = AsyncMock()
        with (
            patch.dict(os.environ, {"APPDATA": tempfile.gettempdir()}, clear=True),
            patch("sys.argv", ["openasrinput", "settings", "--no-open"]),
            patch("openasrinput.presentation.settings_server.serve", serve),
        ):
            main()
        self.assertEqual(serve.await_args.kwargs["port"], 10088)
        self.assertFalse(serve.await_args.kwargs["open_window"])
