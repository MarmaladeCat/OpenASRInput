import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from openasrinput.infrastructure.config import ROOT
from openasrinput.infrastructure.desktop import PackageDesktop
from openasrinput.infrastructure.files import FileTransaction, api


class ActivationTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(
            prefix="activation-", dir=ROOT / "test-results"
        )
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)

    @unittest.skipIf(os.name == "nt", "POSIX file permissions")
    def test_restore_preserves_original_bytes_modes_and_user_edits(self):
        target = self.base / "owned.conf"
        target.write_bytes(b"original\n")
        target.chmod(0o640)
        transaction = FileTransaction(self.base / "state")
        transaction.write(target, b"installed\n")
        created = self.base / "new.conf"
        transaction.write(created, b"new")
        target.write_bytes(b"user edit\n")
        retained = FileTransaction(self.base / "state").restore()
        self.assertEqual(target.read_bytes(), b"original\n")
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertFalse(created.exists())
        self.assertEqual(Path(retained[0]["archive"]).read_bytes(), b"user edit\n")

    @unittest.skipIf(os.name == "nt", "Linux activation symlinks")
    def test_restores_symlinks_without_changing_their_targets(self):
        target = self.base / "original"
        target.write_text("original")
        link = self.base / "link"
        link.symlink_to(target)
        transaction = FileTransaction(self.base / "state")
        transaction.write(link, b"managed")
        self.assertEqual(target.read_text(), "original")
        transaction.restore()
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), target)

    @unittest.skipIf(os.name == "nt", "Linux systemd units")
    def test_package_units_use_installed_entrypoint_and_preserve_config(self):
        config = self.base / "input.json"
        with (
            patch.dict(
                os.environ,
                {
                    "HOME": str(self.base),
                    "XDG_CONFIG_HOME": str(self.base / "config"),
                    "XDG_STATE_HOME": str(self.base / "state"),
                    "OPENASRINPUT_CONFIG": str(config),
                },
            ),
            patch.object(PackageDesktop, "run"),
        ):
            app = PackageDesktop()
            app.setup_units()
            content = (app.units / "openasrinput.service").read_text()
            self.assertIn("/usr/bin/openasrinput", content)
            self.assertIn(
                f'ExecStart="/usr/bin/openasrinput" run-daemon --config "{config}"', content
            )
            self.assertNotIn("WorkingDirectory=", content)
            app.rollback()
            self.assertTrue(config.exists())
            self.assertFalse((app.units / "openasrinput.service").exists())

    def test_authenticated_requests_do_not_follow_redirects(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/target")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with self.assertRaises(HTTPError) as caught:
                api(f"http://127.0.0.1:{server.server_port}/redirect", "test-secret")
            self.assertEqual(caught.exception.code, 302)
            caught.exception.close()
            self.assertEqual(calls, ["/redirect"])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
