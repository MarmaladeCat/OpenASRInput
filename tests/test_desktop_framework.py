import os
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openasrinput import __version__
from openasrinput.infrastructure.config import ROOT, ConfigStore, atomic_json
from openasrinput.infrastructure.desktop import PackageDesktop


@unittest.skipIf(os.name == "nt", "Linux desktop service integration")
class DesktopFrameworkTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "test-results").mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=ROOT / "test-results")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.environment = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / "config"),
            "XDG_STATE_HOME": str(self.home / "state"),
            "XDG_SESSION_TYPE": "x11",
            "OPENASRINPUT_FRAMEWORK": "fcitx4",
            "OPENASRINPUT_SETTINGS_PORT": "10088",
        }
        self.health = {
            "service": "OpenASRInput.Settings",
            "version": __version__,
            "features": ["dictionary-import", "portal-cards", "audio-calibration"],
        }

    def app(self):
        app = PackageDesktop()
        app.store = ConfigStore(self.home / "input.json")
        app.store.save({"runtime": {"socketPath": str(self.home / "bridge.sock")}}, "defaults")
        return app

    def test_fcitx4_activation_and_rollback_manage_both_services(self):
        with (
            patch.dict(os.environ, self.environment),
            patch.object(PackageDesktop, "run") as run,
            patch.object(PackageDesktop, "wait_settings") as ready,
            patch("openasrinput.infrastructure.desktop.webbrowser.open") as browser,
        ):
            app = self.app()
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(self.home / "bridge.sock"))
                app.start()
            config = self.home / "config/fcitx/conf/openasrinput.conf"
            self.assertIn("SocketPath=", config.read_text())
            self.assertFalse((self.home / "config/fcitx5").exists())
            run.assert_any_call("fcitx-remote", "-r")
            run.assert_any_call(
                "systemctl",
                "--user",
                "enable",
                "--now",
                "openasrinput.service",
                "openasrinput-settings.service",
            )
            ready.assert_called_once()
            browser.assert_not_called()
            app.rollback()
            run.assert_any_call(
                "systemctl",
                "--user",
                "disable",
                "openasrinput.service",
                "openasrinput-settings.service",
                check=False,
            )
            self.assertFalse(config.exists())
            self.assertFalse(any(call.args[0] == "gdbus" for call in run.call_args_list))

    def test_fcitx4_rejects_wayland_before_modifying_user_configuration(self):
        with (
            patch.dict(os.environ, {**self.environment, "XDG_SESSION_TYPE": "wayland"}),
            patch.object(PackageDesktop, "run") as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "X11"):
                PackageDesktop().start()
            run.assert_not_called()
            self.assertFalse((self.home / "config").exists())

    def test_fcitx5_activation_stops_old_services_before_replacing_plugin(self):
        with (
            patch.dict(os.environ, {**self.environment, "OPENASRINPUT_FRAMEWORK": "fcitx5"}),
            patch.object(PackageDesktop, "run") as run,
            patch.object(PackageDesktop, "wait_settings"),
        ):
            app = self.app()
            ready = app.state / "settings-ready.json"
            atomic_json(ready, {"url": "http://127.0.0.1:10088/#token=old"})
            path = self.home / "bridge.sock"
            with socket.socket(socket.AF_UNIX) as old, socket.socket(socket.AF_UNIX) as new:
                old.bind(str(path))

                def command(*args, **kwargs):
                    if args[0] == "gdbus":
                        self.assertEqual(args[-1], "org.fcitx.Fcitx.Controller1.Restart")
                        run.assert_any_call(
                            "systemctl",
                            "--user",
                            "stop",
                            "openasrinput.service",
                            "openasrinput-settings.service",
                        )
                        self.assertFalse(ready.exists())
                        path.unlink()
                        new.bind(str(path))

                run.side_effect = command
                app.start()
            self.assertEqual(
                run.call_args.args,
                (
                    "systemctl",
                    "--user",
                    "enable",
                    "--now",
                    "openasrinput.service",
                    "openasrinput-settings.service",
                ),
            )

    def test_fcitx5_activation_does_not_accept_old_socket(self):
        with (
            patch.dict(os.environ, {**self.environment, "OPENASRINPUT_FRAMEWORK": "fcitx5"}),
            patch.object(PackageDesktop, "run") as run,
            patch("openasrinput.infrastructure.desktop.time.sleep"),
        ):
            app = self.app()
            with socket.socket(socket.AF_UNIX) as old:
                old.bind(str(self.home / "bridge.sock"))
                with self.assertRaisesRegex(RuntimeError, "原生桥接未就绪"):
                    app.start()
            self.assertFalse(any("enable" in call.args for call in run.call_args_list))

    def test_stop_stops_both_services_and_invalidates_ready_record(self):
        with patch.dict(os.environ, self.environment), patch.object(PackageDesktop, "run") as run:
            app = self.app()
            ready = app.state / "settings-ready.json"
            atomic_json(ready, {"url": "old"})
            original = app.store.path.read_bytes()
            app.stop()
            run.assert_called_once_with(
                "systemctl",
                "--user",
                "stop",
                "openasrinput.service",
                "openasrinput-settings.service",
            )
            self.assertFalse(ready.exists())
            self.assertEqual(app.store.path.read_bytes(), original)

    def test_settings_only_opens_browser_and_preserves_token(self):
        with (
            patch.dict(os.environ, self.environment),
            patch.object(PackageDesktop, "run", return_value=SimpleNamespace(returncode=0)) as run,
            patch("openasrinput.infrastructure.desktop.api", return_value=self.health),
            patch("openasrinput.infrastructure.desktop.request_bytes", return_value=b"resource"),
            patch(
                "openasrinput.infrastructure.desktop.webbrowser.open", return_value=True
            ) as browser,
        ):
            app = self.app()
            url = "http://127.0.0.1:10088/#token=existing-session"
            ready = app.state / "settings-ready.json"
            atomic_json(ready, {"url": url})
            before = ready.read_bytes()
            app.settings()
            browser.assert_called_once_with(url)
            run.assert_called_once_with(
                "systemctl",
                "--user",
                "is-active",
                "--quiet",
                "openasrinput-settings.service",
                check=False,
            )
            self.assertEqual(ready.read_bytes(), before)
            self.assertFalse(app.units.exists())

    def test_settings_reports_stopped_service_even_with_a_stale_ready_record(self):
        with (
            patch.dict(os.environ, self.environment),
            patch.object(PackageDesktop, "run", return_value=SimpleNamespace(returncode=3)) as run,
            patch("openasrinput.infrastructure.desktop.api") as api,
            patch("openasrinput.infrastructure.desktop.webbrowser.open") as browser,
        ):
            app = self.app()
            atomic_json(
                app.state / "settings-ready.json", {"url": "http://127.0.0.1:10088/#token=old"}
            )
            with self.assertRaisesRegex(RuntimeError, "openasrinput start"):
                app.settings()
            self.assertEqual(run.call_count, 1)
            api.assert_not_called()
            browser.assert_not_called()

    def test_settings_rejects_old_backend_and_missing_calibration_module_without_restart(self):
        with (
            patch.dict(os.environ, self.environment),
            patch.object(PackageDesktop, "run", return_value=SimpleNamespace(returncode=0)) as run,
            patch("openasrinput.infrastructure.desktop.api") as api,
            patch(
                "openasrinput.infrastructure.desktop.request_bytes", return_value=b"resource"
            ) as resource,
            patch("openasrinput.infrastructure.desktop.webbrowser.open") as browser,
        ):
            app = self.app()
            atomic_json(
                app.state / "settings-ready.json", {"url": "http://127.0.0.1:10088/#token=old"}
            )
            cases = [
                {**self.health, "version": "0.9.3"},
                {**self.health, "features": ["dictionary-import", "portal-cards"]},
                self.health,
            ]
            for health in cases:
                api.return_value = health

                def assets(url, **kwargs):
                    if url.endswith("audio-calibration.mjs"):
                        raise OSError("404")
                    return b"resource"

                resource.side_effect = assets
                with (
                    self.subTest(health=health),
                    self.assertRaisesRegex(RuntimeError, "openasrinput start"),
                ):
                    app.settings()
            browser.assert_not_called()
            self.assertTrue(all("is-active" in call.args for call in run.call_args_list))

    def test_settings_does_not_follow_foreign_or_wrong_port_ready_address(self):
        with (
            patch.dict(os.environ, self.environment),
            patch("openasrinput.infrastructure.desktop.api") as api,
        ):
            app = self.app()
            ready = app.state / "settings-ready.json"
            for url in (
                "https://other.invalid/#token=secret",
                "http://127.0.0.1:1234/#token=secret",
                "http://127.0.0.1:10088/#token=",
                "http://127.0.0.1:10088/admin#token=secret",
            ):
                atomic_json(ready, {"url": url})
                with self.subTest(url=url), self.assertRaises(ValueError):
                    app.settings_url(ready)
            api.assert_not_called()

    def test_start_fails_on_settings_readiness_timeout_and_stops_both_services(self):
        with (
            patch.dict(os.environ, self.environment),
            patch.object(PackageDesktop, "run") as run,
            patch.object(PackageDesktop, "wait_settings", side_effect=RuntimeError("10088")),
            patch("openasrinput.infrastructure.desktop.webbrowser.open") as browser,
        ):
            app = self.app()
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(self.home / "bridge.sock"))
                with self.assertRaisesRegex(RuntimeError, "10088"):
                    app.start()
            self.assertEqual(
                run.call_args.args,
                (
                    "systemctl",
                    "--user",
                    "stop",
                    "openasrinput.service",
                    "openasrinput-settings.service",
                ),
            )
            browser.assert_not_called()

    def test_wait_settings_keeps_fixed_port_and_does_not_accept_old_server(self):
        with (
            patch.dict(os.environ, self.environment),
            patch("openasrinput.infrastructure.desktop.api", return_value={}),
            patch("openasrinput.infrastructure.desktop.time.monotonic", side_effect=[0, 0, 11]),
            patch("openasrinput.infrastructure.desktop.time.sleep"),
        ):
            app = self.app()
            atomic_json(
                app.state / "settings-ready.json", {"url": "http://127.0.0.1:10088/#token=old"}
            )
            with self.assertRaisesRegex(RuntimeError, "10088"):
                app.wait_settings()

    def test_saved_ibus_selection_uses_isolated_helper_and_service_socket(self):
        environment = {**self.environment, "OPENASRINPUT_APP_ROOT": str(self.home / "app")}
        with (
            patch.dict(os.environ, environment),
            patch.object(PackageDesktop, "run") as run,
            patch.object(PackageDesktop, "wait_settings"),
        ):
            app = self.app()
            config, revision = app.store.read()
            app.store.save({"input": {"framework": "ibus"}}, revision)
            helper = self.home / "app/ibus/engine.py"
            helper.parent.mkdir(parents=True)
            helper.write_text("# test helper")
            with socket.socket(socket.AF_UNIX) as server:

                def command(*args, **kwargs):
                    if args == ("systemctl", "--user", "start", "openasrinput-ibus.service"):
                        server.bind(config["runtime"]["socketPath"])

                run.side_effect = command
                app.start()
                self.assertEqual(app.framework, "ibus")
                self.assertIn(
                    "Wants=openasrinput-ibus.service",
                    (app.units / "openasrinput.service").read_text(),
                )
                self.assertTrue((app.units / "openasrinput-ibus.service").exists())
                self.assertFalse((app.config_dir / "fcitx").exists())
                app.stop()
                run.assert_any_call(
                    "systemctl", "--user", "stop", "openasrinput-ibus.service", check=False
                )

    def test_ambiguous_auto_selection_leaves_settings_available(self):
        with (
            patch.dict(
                os.environ,
                {
                    **self.environment,
                    "OPENASRINPUT_FRAMEWORK": "auto",
                    "OPENASRINPUT_PACKAGE_FRAMEWORK": "auto",
                },
            ),
            patch.object(PackageDesktop, "run") as run,
            patch(
                "openasrinput.infrastructure.desktop.select_framework",
                side_effect=RuntimeError("ambiguous"),
            ),
        ):
            app = self.app()
            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                app.start()
            run.assert_any_call(
                "systemctl", "--user", "enable", "--now", "openasrinput-settings.service"
            )
            self.assertFalse(
                any("openasrinput.service" in call.args for call in run.call_args_list)
            )

    def test_unified_package_routes_daemon_to_selected_framework_socket(self):
        with (
            patch.dict(os.environ, {**self.environment, "OPENASRINPUT_PACKAGE_FRAMEWORK": "auto"}),
            patch.object(PackageDesktop, "run") as run,
            patch.object(PackageDesktop, "wait_settings"),
        ):
            os.environ.pop("OPENASRINPUT_FRAMEWORK", None)
            app = self.app()
            _, revision = app.store.read()
            app.store.save(
                {"input": {"framework": "fcitx5"}, "runtime": {"socketPath": str(self.home / "b")}},
                revision,
            )
            with socket.socket(socket.AF_UNIX) as server:

                def command(*args, **kwargs):
                    if args[0] == "gdbus":
                        server.bind(str(self.home / "b.fcitx5"))

                run.side_effect = command
                app.start()
            unit = (app.units / "openasrinput.service").read_text()
            self.assertIn("b.fcitx5", unit)
            self.assertIn("OPENASRINPUT_ACTIVE_FRAMEWORK=fcitx5", unit)
            self.assertIn(
                "b.fcitx5", (app.config_dir / "fcitx5/conf/openasrinput.conf").read_text()
            )
