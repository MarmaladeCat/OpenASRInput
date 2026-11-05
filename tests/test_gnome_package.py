"""The installed legacy loader must run the same real panel lifecycle contract."""

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_gnome", ROOT / "scripts/package_gnome.py")
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class GnomePackageTests(unittest.TestCase):
    def test_disjoint_loaders_share_lifecycle(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "test-results") as directory:
            destination = Path(directory)
            package.package_extensions(destination)
            modern = json.loads((destination / "openasrinput@local/metadata.json").read_text())
            legacy = destination / package.LEGACY_UUID
            metadata = json.loads((legacy / "metadata.json").read_text())
            self.assertFalse(set(metadata["shell-version"]) & set(modern["shell-version"]))
            self.assertIn("42", metadata["shell-version"])
            source = (legacy / "extension.js").read_text()
            self.assertNotRegex(source, r"(?m)^export ")
            self.assertNotRegex(source, r"(?m)^import ")
            self.assertNotIn("?.", source)
            self.assertNotIn("??", source)
            if shutil.which("node"):
                subprocess.run(
                    [
                        "node",
                        str(ROOT / "tests/test_gnome_lifecycle.mjs"),
                        str(legacy / "extension.js"),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
