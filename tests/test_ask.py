import unittest

from radbinical import ask as ask_mod
from radbinical import prices
from radbinical.ask import MOCK_DEFAULT, ask, ask_json, extract_json
from test_routing import keys


class Ask(unittest.TestCase):
    def setUp(self):
        prices.TABLE = {}  # no estimates, so usage is exactly what the provider reported

    def tearDown(self):
        ask_mod.HOOK = None
        prices.TABLE = None

    def test_mock_reply_line(self):
        self.assertEqual(ask("mock:judge", "sys", "Some page.\nMOCK_REPLY:  caught in round 2 \nmore"),
                         ("caught in round 2", {"via": "mock"}))

    def test_mock_default(self):
        self.assertEqual(ask("mock:judge", "sys", "no instruction here"), (MOCK_DEFAULT, {"via": "mock"}))

    def test_ask_json_with_mock(self):
        obj, usage = ask_json("mock:x", "sys", 'MOCK_REPLY: Sure. ```json {"verdict": "caught", "by": ["c3"]} ```')
        self.assertEqual(obj, {"verdict": "caught", "by": ["c3"]})
        with self.assertRaises(ValueError):
            ask_json("mock:x", "sys", "nothing to parse")

    def test_extract_json(self):
        self.assertEqual(extract_json('Here [is] it:\n```json\n[1, {"a": "}"}]\n```'), [1, {"a": "}"}])
        self.assertEqual(extract_json('{"a": 1} and {"b": 2}'), {"a": 1})
        with self.assertRaises(ValueError):
            extract_json("{not json}")

    def test_hook_replaces_every_call(self):
        seen = []
        ask_mod.HOOK = lambda model, system, user, max_tokens, temperature: (seen.append(model) or '{"ok": true}', {"cost": 0.01})
        self.assertEqual(ask_json("anthropic:claude-opus-5-5", "s", "u"), ({"ok": True}, {"cost": 0.01}))
        self.assertEqual(ask("mock:x", "s", "MOCK_REPLY: ignored")[0], '{"ok": true}')
        self.assertEqual(seen, ["anthropic:claude-opus-5-5", "mock:x"])

    def test_real_providers_get_no_tools(self):
        import radbinical.providers.chat as chat_mod
        import radbinical.providers.responses as resp_mod
        sent = []
        def fake(url, env, body):
            sent.append((url, body))
            if "responses" in url:
                return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "sol"}]}],
                        "usage": {"input_tokens": 3, "output_tokens": 1}}
            return {"choices": [{"message": {"content": "hi"}}], "usage": {"cost": 0.2}}
        real = chat_mod.post_json, resp_mod.post_json
        chat_mod.post_json = resp_mod.post_json = fake
        try:
            with keys("OPENAI_API_KEY"):
                self.assertEqual(ask("qwen/qwen3.8-27b", "s", "u", temperature=0.5), ("hi", {"cost": 0.2, "via": "openrouter"}))
                self.assertEqual(ask("openai:gpt-6.1-sol", "s", "u"), ("sol", {"prompt_tokens": 3, "completion_tokens": 1, "via": "openai"}))
        finally:
            chat_mod.post_json, resp_mod.post_json = real
        (u1, b1), (u2, b2) = sent
        self.assertIn("openrouter", u1)
        self.assertEqual((b1["model"], b1["temperature"], b1["max_tokens"]), ("qwen/qwen3.8-27b", 0.5, 4000))
        self.assertIn("responses", u2)
        self.assertNotIn("tools", b1)
        self.assertNotIn("tools", b2)

    def test_answer_cut_off_while_reasoning_raises(self):
        import radbinical.providers.chat as chat_mod
        real = chat_mod.post_json
        chat_mod.post_json = lambda url, env, body: {"choices": [{"message": {"content": None, "reasoning": "..."},
                                                                  "finish_reason": "length"}], "usage": {"cost": 0.3}}
        try:
            with self.assertRaises(ask_mod.Truncated) as e:
                ask("qwen/qwen3.8-27b", "s", "u", max_tokens=50)
        finally:
            chat_mod.post_json = real
        self.assertIn("max_tokens=50", str(e.exception))
        self.assertEqual(e.exception.usage["cost"], 0.3)


if __name__ == "__main__":
    unittest.main()
