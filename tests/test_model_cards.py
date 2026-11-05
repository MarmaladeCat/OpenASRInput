import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from openasrinput.infrastructure.config import ConfigStore, atomic_json
from openasrinput.presentation.settings_server import SettingsServer


def card(identity="one", **fields):
    value = dict(
        id=identity,
        name=identity,
        provider="openai-compatible",
        url="http://localhost/v1",
        model="org/model:latest",
        apiKey="fixture-key",
    )
    value.update(fields)
    return value


class CardsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ConfigStore(Path(self.temp.name) / "input.json")

    def save(self, **fields):
        return self.store.save({"textEdit": fields}, self.store.read()[1])

    def test_secrets_are_per_card_and_incomplete_cards_are_rejected(self):
        self.save(
            cards=[card(apiKey="secret-a"), card("two", apiKey="secret-b")], activeModelCardId="one"
        )
        public = self.store.public()["config"]["textEdit"]
        self.assertNotIn("secret-", json.dumps(public))
        public_cards = [{k: v for k, v in c.items() if k != "hasApiKey"} for c in public["cards"]]
        public_cards[0]["clearApiKey"] = True
        with self.assertRaisesRegex(ValueError, "API Key"):
            self.save(cards=public_cards, activeModelCardId="two")
        public_cards[0].pop("clearApiKey")
        self.save(cards=public_cards, activeModelCardId="two")
        saved = self.store.read()[0]["textEdit"]
        self.assertEqual([c["apiKey"] for c in saved["cards"]], ["secret-a", "secret-b"])
        self.assertEqual(saved["apiKey"], "secret-b")
        draft = card("draft")
        draft.update(url="", model="")
        with self.assertRaisesRegex(ValueError, "配置完整"):
            self.save(cards=[draft], activeModelCardId="draft")
        self.assertEqual(self.store.read()[0]["textEdit"], saved)

    def test_legacy_migration_preserves_custom_gateway_and_backup(self):
        old = {
            "textEdit": {
                "provider": "deepseek",
                "url": "https://gateway.example/v1",
                "model": "old-model",
                "apiKey": "old-secret",
            }
        }
        self.store.path.write_text(json.dumps(old))
        first, _ = self.store.read()
        self.assertEqual(first["textEdit"]["cards"][0]["provider"], "openai-compatible")
        self.save(activeModelCardId="legacy")
        self.assertEqual(
            json.loads(self.store.path.with_suffix(".pre-model-cards.json").read_text()), old
        )
        self.assertEqual(len(self.store.read()[0]["textEdit"]["cards"]), 1)

    def test_invalid_reference_and_duplicate_id_rejected(self):
        for cards, active in [([card(), card()], "one"), ([card()], "missing")]:
            with self.assertRaises(ValueError):
                self.save(cards=cards, activeModelCardId=active)
        self.save(cards=[card(), card("two")], activeModelCardId="one")
        with self.assertRaises(ValueError):
            self.save(model="old-client-update")
        self.assertEqual(len(self.store.read()[0]["textEdit"]["cards"]), 2)

    def test_cached_results_follow_connection_not_other_cards(self):
        original = card(apiKey="private-key")
        self.save(cards=[original], activeModelCardId="one")
        self.store.record_model_result(original, "test", {"ok": False, "error": "HTTP 403"})
        self.store.record_model_result(original, "models", {"models": ["org/model:latest"]})
        public = self.store.public()
        self.assertFalse(public["modelCardMetadata"]["one"]["test"]["ok"])
        self.assertNotIn("private-key", json.dumps(public))
        changed = dict(original, model="new-model")
        self.save(cards=[changed], activeModelCardId="one")
        metadata = self.store.public()["modelCardMetadata"]["one"]
        self.assertNotIn("test", metadata)
        self.assertIn("models", metadata)
        self.save(cards=[dict(changed, apiKey="other-key")], activeModelCardId="one")
        self.assertEqual(self.store.public()["modelCardMetadata"]["one"], {})

    def test_old_incomplete_cards_can_be_repaired_individually(self):
        one, two = card(model=""), card("two", model="")
        self.store.path.write_text(
            json.dumps({"textEdit": {"cards": [one, two], "activeModelCardId": ""}})
        )
        with self.assertRaisesRegex(ValueError, "配置完整"):
            self.save(activeModelCardId="two")
        self.save(cards=[dict(one, model="configured"), two], activeModelCardId="one")
        self.assertEqual(self.store.read()[0]["textEdit"]["cards"][1]["model"], "")
        self.save(cards=[dict(one, model="configured")], activeModelCardId="one")

    def test_unicode_cards_can_be_saved_again_and_legacy_backup_is_lossless(self):
        old = {
            "textEdit": {"apiKey": "old-secret"},
            "custom": {"note": "中文配置🙂"},
        }
        atomic_json(self.store.path, old)
        self.save(activeModelCardId="legacy")
        self.assertEqual(
            json.loads(self.store.path.with_suffix(".pre-model-cards.json").read_bytes()), old
        )
        self.save(cards=[card(name="本地润色🙂")], activeModelCardId="one")
        self.save(activeModelCardId="")
        self.assertEqual(self.store.read()[0]["textEdit"]["cards"][0]["name"], "本地润色🙂")

    def test_unicode_metadata_survives_reload_and_another_card_result(self):
        first, second = card(name="中文卡🙂"), card("two")
        self.save(cards=[first, second], activeModelCardId="one")
        self.store.record_model_result(first, "test", {"ok": False, "error": "连接失败🙂"})
        self.store.record_model_result(second, "models", {"models": ["中文模型"]})
        metadata = ConfigStore(self.store.path).public()["modelCardMetadata"]
        self.assertEqual(metadata["one"]["test"]["error"], "连接失败🙂")
        self.assertEqual(metadata["two"]["models"]["models"], ["中文模型"])

    def test_invalid_optional_cache_entry_does_not_block_settings_or_retesting(self):
        first = card()
        self.save(cards=[first], activeModelCardId="one")
        atomic_json(self.store.path.with_suffix(".models.json"), {"one": None})
        self.assertEqual(self.store.public()["modelCardMetadata"]["one"], {})
        self.store.record_model_result(first, "test", {"ok": True})
        self.assertTrue(self.store.public()["modelCardMetadata"]["one"]["test"]["ok"])


class CardApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ConfigStore(Path(self.temp.name) / "input.json")
        self.calls = []

        async def models(request):
            self.calls.append(request.headers.get("Authorization"))
            return web.json_response({"data": [{"id": "org/model:latest"}]})

        async def completion(request):
            self.calls.append(request.headers.get("Authorization"))
            body = await request.json()
            self.assertNotIn("thinking", body)
            return web.json_response(
                {"choices": [{"finish_reason": "stop", "message": {"content": "您好！"}}]}
            )

        upstream = web.Application()
        upstream.router.add_get("/v1/models", models)
        upstream.router.add_post("/v1/chat/completions", completion)
        self.upstream = TestServer(upstream)
        await self.upstream.start_server()
        self.addAsyncCleanup(self.upstream.close)
        settings = SettingsServer(self.store)
        self.client = TestClient(
            TestServer(settings.app()), headers={"Authorization": "Bearer " + settings.token}
        )
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_draft_test_and_discovery_do_not_save(self):
        draft = card()
        draft["url"] = str(self.upstream.make_url("/v1"))
        for action in ("models", "test"):
            response = await self.client.post(
                "/api/text-model/" + action, json={"card": draft, "revision": "defaults"}
            )
            self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(self.calls, ["Bearer fixture-key", "Bearer fixture-key"])
        self.assertFalse(self.store.path.exists())
        response = await self.client.post(
            "/api/text-model/test", json={"card": draft, "revision": "stale"}
        )
        self.assertEqual(response.status, 409)
