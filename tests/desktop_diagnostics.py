"""Read-only readiness and optional tracing in the disposable GNOME desktop."""

import ast
import json
import os
import subprocess
from pathlib import Path

UUID = "openasrinput-test-trace@local"


def gnome_state():
    result = subprocess.run(
        [
            "gdbus",
            "call",
            "--session",
            "--dest",
            "org.openasrinput.DesktopTest",
            "--object-path",
            "/org/openasrinput/DesktopTest",
            "--method",
            "org.openasrinput.DesktopTest.Describe",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode:
        return {}
    return json.loads(ast.literal_eval(result.stdout)[0])


def install_gnome_probe(version):
    assert Path("/.dockerenv").exists() and os.environ.get("HOME") == "/tmp/desktop-home"
    directory = Path(os.environ["XDG_DATA_HOME"]) / "gnome-shell/extensions" / UUID
    directory.mkdir(parents=True)
    (directory / "metadata.json").write_text(
        json.dumps(
            {
                "uuid": UUID,
                "name": "Disposable desktop trace",
                "description": "Read-only focus and Shell state in the isolated test session",
                "shell-version": [version],
            }
        )
    )
    body = """
const XML = `<node><interface name="org.openasrinput.DesktopTest">
    <method name="Describe"><arg type="s" direction="out"/></method>
</interface></node>`;
class DesktopTrace {
    Describe() {
            const window = global.display.focus_window;
            const focus = global.stage.get_key_focus();
            const keyboard = Main.panel.statusArea.keyboard;
            const source = keyboard ? keyboard._inputSourceManager.currentSource : null;
            return JSON.stringify({
                window: window ? window.get_title() : null,
                keyFocus: focus ? focus.toString() : null,
                overview: Main.overview.visible,
                startingUp: Main.layoutManager._startingUp,
                modalCount: Main.modalCount,
                locked: Main.sessionMode.isLocked,
                shieldActive: Main.screenShield ? Main.screenShield._isActive : null,
                inputSource: source ? source.id : null,
                windows: global.get_window_actors().map(actor => ({
                    title: actor.meta_window.get_title(),
                    visible: actor.visible,
                    mapped: actor.mapped,
                    opacity: actor.opacity,
                    workspace: actor.meta_window.get_workspace().index(),
                })),
            });
    }
    enable() {
        this.exported = Gio.DBusExportedObject.wrapJSObject(XML, this);
        this.exported.export(Gio.DBus.session, '/org/openasrinput/DesktopTest');
        this.name = Gio.bus_own_name_on_connection(Gio.DBus.session,
            'org.openasrinput.DesktopTest', Gio.BusNameOwnerFlags.NONE, null, null);
        if (GLib.getenv('OPENASRINPUT_TRACE_DESKTOP') !== '1') return;
        let previous = '';
        this.timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 250, () => {
            const state = this.Describe();
            if (state !== previous) {
                log('DESKTOP_TRACE ' + GLib.get_monotonic_time() + ' ' + state);
                previous = state;
            }
            return GLib.SOURCE_CONTINUE;
        });
    }
    disable() {
        if (this.timer) GLib.source_remove(this.timer);
        this.exported.unexport();
        Gio.bus_unown_name(this.name);
    }
}
"""
    if int(version.split(".")[0]) >= 45:
        source = (
            "import GLib from 'gi://GLib';\nimport Gio from 'gi://Gio';\n"
            "import * as Main from 'resource:///org/gnome/shell/ui/main.js';\n"
            + body.replace("class DesktopTrace", "export default class DesktopTrace")
        )
    else:
        source = (
            "const { GLib, Gio } = imports.gi;\nconst Main = imports.ui.main;\n"
            + body
            + "\nfunction init() { return new DesktopTrace(); }\n"
        )
    (directory / "extension.js").write_text(source)
    return UUID
