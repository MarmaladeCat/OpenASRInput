"""The reserved product logo is shared by settings, native tray and installers."""

import importlib.util
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

from openasrinput.presentation.settings_server import BRANDING, SettingsServer

ROOT = Path(__file__).resolve().parents[1]


class BrandingHTTPTests(AioHTTPTestCase):
    async def get_application(self):
        return SettingsServer().app()

    async def test_logo_is_public_local_and_csp_compatible(self):
        response = await self.client.get("/branding/logo.svg")
        self.assertEqual(response.status, 200)
        self.assertIn("image/svg+xml", response.headers["Content-Type"])
        self.assertEqual(await response.read(), (BRANDING / "logo.svg").read_bytes())
        self.assertIn("img-src 'self'", response.headers["Content-Security-Policy"])
        page = await self.client.get("/")
        html = await page.text()
        self.assertIn('src="/branding/logo.svg"', html)
        self.assertIn('rel="icon" href="/branding/logo.svg"', html)
        self.assertNotIn('class="brand-mark">◉', html)


class BrandingPackagingTests(unittest.TestCase):
    def test_windows_logo_is_optional_and_input_is_not_a_system_service(self):
        spec = importlib.util.spec_from_file_location(
            "input_windows_build", ROOT / "scripts/build_windows.py"
        )
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        results = ROOT / "test-results"
        results.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="branding-", dir=results) as temporary:
            directory = Path(temporary)
            payload = directory / "payload"
            logo = payload / "app/openasrinput/presentation/branding/logo.ico"
            logo.parent.mkdir(parents=True)
            (payload / "OpenASRInput.exe").touch()
            for branded in (False, True):
                if branded:
                    logo.write_bytes(b"icon-placeholder-for-xml-test")
                filename = directory / "input.wxs"
                build.wix(payload, filename)
                root = ET.parse(filename).getroot()
                ns = {"w": "http://schemas.microsoft.com/wix/2006/wi"}
                self.assertFalse(root.findall(".//w:ServiceInstall", ns))
                self.assertEqual(root.find(".//w:Package", ns).get("InstallScope"), "perUser")
                self.assertEqual(bool(root.findall(".//w:Icon", ns)), branded)
                for shortcut in root.findall(".//w:Shortcut", ns):
                    self.assertEqual(shortcut.get("Icon"), "ProductLogo" if branded else None)


if __name__ == "__main__":
    unittest.main()
