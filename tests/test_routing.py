import os
import unittest
from unittest import mock

from radbinical.config import DEFAULT_FLAGS
from radbinical.page import cast_of
from radbinical.providers import ChatSession, canonical, open_session, route
from radbinical.providers.claude import AnthropicSession
from radbinical.providers.http import KEYS
from radbinical.providers.responses import ResponsesSession


def keys(*set_names):
    """Patch the environment so that exactly these key variables are set."""
    every = {n: "" for names in KEYS.values() for n in names}
    return mock.patch.dict(os.environ, {**every, **{n: "k" for n in set_names}})


class Route(unittest.TestCase):
    def test_shared_ids_go_to_nous_ahead_of_openrouter(self):
        with keys("NOUS_API_KEY"):
            self.assertEqual(route("moonshotai/kimi-k3"), ("nous", "moonshotai/kimi-k3"))
        with keys("NOUS_API_KEY", "OPENROUTER_API_KEY"):
            self.assertEqual(route("moonshotai/kimi-k3"), ("nous", "moonshotai/kimi-k3"))
            self.assertEqual(route("openrouter:moonshotai/kimi-k3"), ("openrouter", "moonshotai/kimi-k3"))
        with keys("OPENROUTER_API_KEY"):
            self.assertEqual(route("moonshotai/kimi-k3"), ("openrouter", "moonshotai/kimi-k3"))

    def test_native_models_go_to_their_maker(self):
        with keys("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY", "NVIDIA_API_KEY", "NOUS_API_KEY", "OPENROUTER_API_KEY"):
            self.assertEqual(route("openai/gpt-6.1-terra"), ("openai", "gpt-6.1-terra"))
            self.assertEqual(route("google/gemini-4-argon"), ("google", "gemini-4-argon"))
            self.assertEqual(route("anthropic/claude-opus-5.5"), ("anthropic", "claude-opus-5-5"))
            self.assertEqual(route("x-ai/grok-4.7"), ("xai", "grok-4.7"))
            self.assertEqual(route("xai:grok-4.7"), ("xai", "grok-4.7"))
            self.assertEqual(route("nvidia/nemotron-3-ultra-550b-a55b"), ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"))

    def test_native_models_never_fall_back_to_a_shared_provider(self):
        with keys("NOUS_API_KEY", "OPENROUTER_API_KEY"):
            for model, key in (("openai/gpt-6.1-terra", "OPENAI_API_KEY"), ("anthropic/claude-opus-5.5", "ANTHROPIC_API_KEY"),
                               ("google/gemini-4-argon", "GEMINI_API_KEY"), ("x-ai/grok-4.7", "XAI_API_KEY"),
                               ("anthropic:claude-opus-5-5", "ANTHROPIC_API_KEY"), ("openai:gpt-6.1-sol", "OPENAI_API_KEY"),
                               ("google:gemini-4-argon", "GEMINI_API_KEY"), ("xai:grok-4.7", "XAI_API_KEY")):
                with self.assertRaisesRegex(RuntimeError, f"set {key}.*only sent to its maker"):
                    route(model)

    def test_a_shared_provider_named_in_the_id_is_used(self):
        with keys("NOUS_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
            self.assertEqual(route("nous:google/gemini-4-argon"), ("nous", "google/gemini-4-argon"))
            self.assertEqual(route("openrouter:openai/gpt-6.1-terra"), ("openrouter", "openai/gpt-6.1-terra"))
            self.assertEqual(route("openai/gpt-oss-120b"), ("nous", "openai/gpt-oss-120b"))
            self.assertEqual(route("google/gemini-4-argon:free"), ("nous", "google/gemini-4-argon:free"))

    def test_nim_key_is_another_name_for_nvidia(self):
        with keys("NVIDIA_NIM_API_KEY"):
            self.assertEqual(route("nvidia:nvidia/x"), ("nvidia", "nvidia/x"))
            self.assertEqual(route("nvidia/x"), ("nvidia", "nvidia/x"))

    def test_explicit_prefix_wins(self):
        with keys("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            self.assertEqual(route("anthropic:claude-opus-5-5"), ("anthropic", "claude-opus-5-5"))
            self.assertEqual(route("google:gemini-4-argon"), ("google", "gemini-4-argon"))
            self.assertEqual(route("mock:alef"), ("mock", "alef"))

    def test_nvidia_goes_shared_without_its_key(self):
        with keys("OPENROUTER_API_KEY"):
            self.assertEqual(route("nvidia:nvidia/x"), ("openrouter", "nvidia/x"))
            self.assertEqual(route("nvidia/x"), ("openrouter", "nvidia/x"))
            with self.assertRaisesRegex(RuntimeError, "NVIDIA_API_KEY or NVIDIA_NIM_API_KEY"):
                route("nvidia:meta/llama-9")   # no OpenRouter form

    def test_missing_key_fails_clearly(self):
        with keys():
            with self.assertRaisesRegex(RuntimeError, "set ANTHROPIC_API_KEY"):
                route("anthropic:claude-opus-5-5")
            with self.assertRaisesRegex(RuntimeError, "NVIDIA_API_KEY.*OPENROUTER_API_KEY"):
                route("nvidia:nvidia/x")
            self.assertEqual(route("mock:alef"), ("mock", "alef"))
            self.assertEqual(route("qwen/qwen3.8-27b"), ("openrouter", "qwen/qwen3.8-27b"))

    def test_sessions_follow_the_route(self):
        flags = dict(DEFAULT_FLAGS)
        with keys("GEMINI_API_KEY", "OPENAI_API_KEY"):
            s = open_session({"model": "google/gemini-4-argon"}, "s", "u", flags)
            self.assertIsInstance(s, ChatSession)
            self.assertEqual((s.via, s.name, s.cap), ("google", "gemini-4-argon", "max_tokens"))
            self.assertIn("generativelanguage.googleapis.com", s.url)
            self.assertIsInstance(open_session({"model": "openai/gpt-6.1-terra"}, "s", "u", flags), ResponsesSession)
        with keys("XAI_API_KEY", "OPENROUTER_API_KEY"):
            s = open_session({"model": "x-ai/grok-4.7"}, "s", "u", flags)
            self.assertEqual((s.via, s.name, s.url), ("xai", "grok-4.7", "https://api.x.ai/v1/chat/completions"))
            s = open_session({"model": "moonshotai/kimi-k3"}, "s", "u", flags)
            self.assertEqual((s.via, s.name), ("openrouter", "moonshotai/kimi-k3"))
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return
        with keys("ANTHROPIC_API_KEY"):
            self.assertIsInstance(open_session({"model": "anthropic/claude-opus-5.5"}, "s", "u", flags), AnthropicSession)


class Canonical(unittest.TestCase):
    def test_one_model_two_spellings(self):
        self.assertEqual(canonical("anthropic:claude-opus-5-5"), "anthropic/claude-opus-5.5")
        self.assertEqual(canonical("anthropic/claude-opus-5-5"), "anthropic/claude-opus-5.5")
        self.assertEqual(canonical("openai:gpt-6.1-sol"), "openai/gpt-6.1-sol")
        self.assertEqual(canonical("nvidia:nvidia/x"), "nvidia/x")
        self.assertEqual(canonical("google:gemini-4-argon"), "google/gemini-4-argon")
        self.assertEqual(canonical("xai:grok-4.7"), "x-ai/grok-4.7")
        self.assertEqual(canonical("x-ai/grok-4.7"), "x-ai/grok-4.7")
        self.assertEqual(canonical("mock:alef"), "mock:alef")
        self.assertEqual(cast_of(["anthropic:claude-opus-5-5", "openai:gpt-6.1-sol"]),
                         cast_of(["openai/gpt-6.1-sol", "anthropic/claude-opus-5.5"]))

    def test_cast_ignores_keys(self):
        with keys():
            a = cast_of(["anthropic:claude-opus-5-5"])
        with keys("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
            self.assertEqual(cast_of(["anthropic/claude-opus-5.5"]), a)


class Anthropic(unittest.TestCase):
    def test_streams_and_reads_the_answer(self):
        from types import SimpleNamespace as NS
        seen = {}
        final = NS(content=[NS(type="thinking", thinking="..."), NS(type="text", text="Done.")],
                   stop_reason="end_turn", usage=NS(input_tokens=10, output_tokens=3))

        class Stream:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get_final_message(self): return final

        class Messages:
            def stream(self, **kw):
                seen.update(kw)
                return Stream()

        s = AnthropicSession.__new__(AnthropicSession)
        s.client, s.name, s.system, s.max_tokens = NS(messages=Messages()), "claude-x", "sys", 24000
        s.flags, s.messages = dict(DEFAULT_FLAGS), [{"role": "user", "content": "u"}]
        self.assertEqual(s.step(), ("Done.", {"prompt_tokens": 10, "completion_tokens": 3}))
        self.assertNotIn("tools", seen)
        s.say("more")
        self.assertEqual([m["role"] for m in s.messages], ["user", "assistant", "user"])
        self.assertEqual((seen["max_tokens"], seen["model"]), (24000, "claude-x"))
        self.assertFalse(s.truncated)


class Retry(unittest.TestCase):
    def test_402_waits_for_retry_after_then_succeeds(self):
        import io
        import urllib.error
        from radbinical.providers import http
        calls, waits = [], []
        def urlopen(req, timeout=None):
            calls.append(1)
            if len(calls) < 3:
                raise urllib.error.HTTPError("u", 402, "in flight", {"Retry-After": "20"}, io.BytesIO(b"{}"))
            class R:
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def read(self): return b'{"choices": [{"message": {"content": "ok"}}]}'
            return R()
        real = http.urllib.request.urlopen, http.time.sleep
        http.urllib.request.urlopen, http.time.sleep = urlopen, waits.append
        try:
            self.assertEqual(http.post_json("http://x", "openrouter", {"model": "m"})["choices"][0]["message"]["content"], "ok")
        finally:
            http.urllib.request.urlopen, http.time.sleep = real
        self.assertEqual([int(w) for w in waits], [20, 20])

    def test_gives_up_after_attempts(self):
        import io
        import urllib.error
        from radbinical.providers import http
        def urlopen(req, timeout=None):
            raise urllib.error.HTTPError("u", 429, "busy", {}, io.BytesIO(b"{}"))
        real = http.urllib.request.urlopen, http.time.sleep
        waits = []
        http.urllib.request.urlopen, http.time.sleep = urlopen, waits.append
        try:
            with self.assertRaises(RuntimeError):
                http.post_json("http://x", "openrouter", {"model": "m"})
        finally:
            http.urllib.request.urlopen, http.time.sleep = real
        self.assertEqual(len(waits), http.ATTEMPTS - 1)
        self.assertTrue(all(w < 61 for w in waits))


if __name__ == "__main__":
    unittest.main()
