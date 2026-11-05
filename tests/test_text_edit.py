import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from openasrinput.adapters.text_edit import TextEditor
from openasrinput.infrastructure.config import normalize


class TextEditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.status = 200
        self.finish = "stop"
        self.content = "Hello world."
        app = web.Application()
        app.router.add_post("/chat/completions", self.reply)
        self.server = TestServer(app)
        await self.server.start_server()
        self.editor = TextEditor(
            {
                "url": str(self.server.make_url("/")).rstrip("/"),
                "model": "deepseek-chat",
                "apiKey": "fixture-secret",
            }
        )

    async def asyncTearDown(self):
        await self.server.close()

    async def reply(self, request):
        self.calls.append((request.headers.get("Authorization"), await request.json()))
        if self.status != 200:
            return web.Response(
                status=self.status,
                text="private-response fixture-secret",
                headers={"Location": "/must-not-follow"},
            )
        return web.json_response(
            {"choices": [{"finish_reason": self.finish, "message": {"content": self.content}}]}
        )

    async def test_success_sends_selected_text_and_instruction_and_returns_only_result(self):
        result = await self.editor.edit("你好世界。", "翻译为英文")
        self.assertEqual(result, "Hello world.")
        self.assertEqual(self.calls[0][0], "Bearer fixture-secret")
        body = self.calls[0][1]
        self.assertFalse(body["stream"])
        self.assertEqual(body["model"], "deepseek-chat")
        self.assertIn("你好世界。", body["messages"][1]["content"])
        self.assertIn("翻译为英文", body["messages"][1]["content"])

    async def test_http_failure_and_redirect_do_not_leak_response_or_follow_redirect(self):
        for code in (302, 401, 429, 500):
            self.status = code
            with self.assertRaises(ValueError) as error:
                await self.editor.edit("private selection", "translate")
            self.assertIn(str(code), str(error.exception))
            self.assertNotIn("fixture-secret", str(error.exception))
            self.assertNotIn("private", str(error.exception))

    async def test_truncated_empty_or_oversized_results_are_never_accepted(self):
        for finish, content in (("length", "partial"), ("stop", ""), ("stop", "x" * 16001)):
            self.finish, self.content = finish, content
            with self.assertRaises(ValueError):
                await self.editor.edit("original", "translate")

    async def test_unconfigured_key_or_invalid_input_does_not_send_request(self):
        self.editor.config["apiKey"] = ""
        with self.assertRaises(ValueError):
            await self.editor.edit("原文", "translate")
        self.assertEqual(self.calls, [])

    def test_default_provider_and_model_are_deepseek(self):
        config = normalize({})["textEdit"]
        self.assertEqual(config["provider"], "deepseek")
        self.assertEqual(config["model"], "deepseek-chat")
        self.assertEqual(config["apiKey"], "")
