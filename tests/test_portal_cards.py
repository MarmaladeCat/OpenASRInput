import json
import tempfile
import unittest
from pathlib import Path

from openasrinput.infrastructure.config import ConfigConflict, ConfigStore
from openasrinput.infrastructure.installed_portal import import_handoff


def card(identity="one", key="one-secret", **fields):
    return {
        "id": identity,
        "name": identity,
        "url": "http://127.0.0.1:10087",
        "apiKey": key,
        "profileId": "",
        **fields,
    }


class PortalCardTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "test-results"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="portal-cards-", dir=root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "input.json"
        self.store = ConfigStore(self.path)

    def save(self, patch):
        return self.store.save({"portal": patch}, self.store.read()[1])

    def test_legacy_connection_is_losslessly_migrated_with_backup(self):
        original = {
            "portal": {
                "url": "http://localhost:12345",
                "apiKey": "legacy-secret",
                "profileId": "local",
            },
            "extension": {"keep": True},
        }
        self.path.write_text(json.dumps(original), encoding="utf-8")
        value = self.store.read()[0]
        self.assertEqual(value["portal"]["cards"][0]["apiKey"], "legacy-secret")
        self.save({"activePortalCardId": "legacy"})
        self.assertEqual(
            json.loads(self.path.with_suffix(".pre-portal-cards.json").read_bytes()), original
        )
        self.assertEqual(self.store.read()[0]["extension"], {"keep": True})

    def test_multiple_cards_active_projection_and_private_keys(self):
        result = self.save(
            {
                "cards": [card(), card("two", "two-secret", url="https://portal.example")],
                "activePortalCardId": "one",
            }
        )
        self.assertNotIn("one-secret", json.dumps(result))
        self.assertNotIn("two-secret", json.dumps(result))
        self.save({"activePortalCardId": "two"})
        self.assertEqual(self.store.read()[0]["portal"]["apiKey"], "two-secret")
        public = result["config"]["portal"]["cards"]
        public = [{k: v for k, v in item.items() if k != "hasApiKey"} for item in public]
        public[0]["apiKey"] = ""
        self.save({"cards": public})
        self.assertEqual(self.store.read()[0]["portal"]["cards"][0]["apiKey"], "one-secret")
        with self.assertRaises(ValueError):
            self.save({"cards": [card("new", "")]})

    def test_cache_is_per_card_and_invalidated_by_connection_change(self):
        self.save({"cards": [card(), card("two", "two-secret")], "activePortalCardId": "one"})
        self.store.record_portal_result(card(), {"ok": True, "elapsedMs": 9})
        self.assertEqual(self.store.public()["portalCardMetadata"]["one"]["elapsedMs"], 9)
        self.save({"cards": [card(key="replacement"), card("two", "two-secret")]})
        self.assertEqual(self.store.public()["portalCardMetadata"], {})
        self.assertNotIn("replacement", self.path.with_suffix(".portals.json").read_text())

    def test_installer_handoff_import_is_idempotent_and_does_not_reset_later_selection(self):
        self.save(
            {
                "cards": [card("remote", "remote-secret", url="https://remote.example")],
                "activePortalCardId": "remote",
            }
        )
        handoff = self.path.with_name("handoff.json")
        handoff.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "generation": "install-generation-1",
                    "portal": card("local-input", "asr_installer-secret"),
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(import_handoff(self.store, handoff))
        self.assertEqual(self.store.read()[0]["portal"]["activePortalCardId"], "local-input")
        self.save({"activePortalCardId": "remote"})
        self.assertFalse(import_handoff(self.store, handoff))
        self.assertEqual(self.store.read()[0]["portal"]["activePortalCardId"], "remote")
        self.assertEqual(len(self.store.read()[0]["portal"]["cards"]), 2)

    def test_invalid_cards_and_stale_revisions_do_not_mutate_config(self):
        self.save({"cards": [card()], "activePortalCardId": "one"})
        original = self.path.read_bytes()
        for patch in (
            {"activePortalCardId": "missing"},
            {"cards": [card(), card()]},
            {"cards": [card(url="file:///private")]},
            {"cards": [card(url="http://user:pass@localhost")]},
        ):
            with self.assertRaises(ValueError):
                self.save(patch)
        with self.assertRaises(ConfigConflict):
            self.store.save({"portal": {"cards": []}}, "stale")
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
