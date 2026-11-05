"""Package one renderer for both pre-45 GJS and modern ESM extension loaders."""

import json
import re
import shutil
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src/native/gnome/openasrinput@local"
LEGACY_UUID = "openasrinput-legacy@local"


def legacy_source():
    # Only the module envelope differs. Geometry, drawing, protocol and lifecycle
    # remain a single source of truth, exercised by the same lifecycle tests.
    panel = (SOURCE / "panel.mjs").read_text(encoding="utf-8")
    panel = re.sub(r"^export ", "", panel, flags=re.M)
    renderer = (SOURCE / "extension.js").read_text(encoding="utf-8")
    renderer = re.sub(r"^import .*;\n", "", renderer, flags=re.M)
    declaration = "export default class VoicePanelExtension extends Extension"
    if renderer.count(declaration) != 1:
        raise ValueError("GNOME renderer module envelope changed")
    renderer = renderer.replace(declaration, "class VoicePanelExtension")
    return (
        "// Generated from the shared renderer; do not edit this installed copy.\n"
        "const Cairo = imports.cairo;\n"
        "const { Gio, GLib, Pango, PangoCairo, St } = imports.gi;\n"
        "const Config = imports.misc.config;\n"
        "const Main = imports.ui.main;\n"
        + panel
        + "\n"
        + renderer
        + "\nfunction init() { return new VoicePanelExtension(); }\n"
    )


def package_extensions(destination):
    shutil.copytree(SOURCE, destination / SOURCE.name)
    legacy = destination / LEGACY_UUID
    legacy.mkdir()
    metadata = json.loads((SOURCE / "metadata.json").read_text(encoding="utf-8"))
    metadata.update(
        uuid=LEGACY_UUID, **{"shell-version": ["3.36", "3.38", "40", "41", "42", "43", "44"]}
    )
    (legacy / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (legacy / "extension.js").write_text(legacy_source(), encoding="utf-8")
