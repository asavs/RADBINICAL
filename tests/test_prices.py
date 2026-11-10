import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical import ask as ask_mod
from radbinical import prices, rounds
from radbinical.cli import main
from radbinical.commands import prices as prices_cmd
from radbinical.page import Page
from radbinical.table import runs
from test_plant import make_page

FAKE = {"anthropic/claude-test-1.5": {"prompt": 1e-06, "completion": 5e-06},
        "openai/gpt-test": {"prompt": 2e-06, "completion": 1e-05}}


def run(argv):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        main(argv)
    return out.getvalue()


class Prices(unittest.TestCase):
    def setUp(self):
        prices.TABLE = dict(FAKE)
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        prices.TABLE = None
        ask_mod.HOOK = None
        self.tmp.cleanup()

    def test_tokens_and_reasoning(self):
        self.assertEqual(prices.tokens({"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}), (10, 4))
        # a total above prompt plus completion: the rest is reasoning left out of completion_tokens
        self.assertEqual(prices.tokens({"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 20}), (10, 10))
        self.assertEqual(prices.tokens({"input_tokens": 7, "output_tokens": 3}), (7, 3))
        self.assertIsNone(prices.tokens({"cost": 1}))
        self.assertIsNone(prices.tokens(None))

    def test_price_by_canonical_id(self):
        u = {"prompt_tokens": 1000, "completion_tokens": 100}
        self.assertAlmostEqual(prices.price("anthropic:claude-test-1-5", u), 0.0015)
        self.assertAlmostEqual(prices.price("anthropic/claude-test-1.5", u), 0.0015)
        self.assertAlmostEqual(prices.price("openai:gpt-test", u), 0.003)
        self.assertIsNone(prices.price("x-ai/unpriced", u))
        self.assertIsNone(prices.price("mock:alef", u))
        self.assertIsNone(prices.price("openai:gpt-test", {}))

    def test_complete(self):
        u = prices.complete("openai:gpt-test", {"prompt_tokens": 1000, "completion_tokens": 100, "via": "openai"})
        self.assertEqual((u["cost"], u["cost_estimated"]), (0.003, True))
        reported = {"prompt_tokens": 1000, "completion_tokens": 100, "cost": 0.5}
        self.assertEqual(prices.complete("openai:gpt-test", dict(reported)), reported)
        self.assertEqual(prices.complete("x-ai/unpriced", {"prompt_tokens": 5}), {"prompt_tokens": 5})
        self.assertEqual(prices.costs([{"cost": 0.5}, {"cost": 0.25, "cost_estimated": True}, {}, "junk"]), (0.5, 0.25))

    def test_ask_estimates_when_no_cost(self):
        ask_mod.HOOK = lambda *a: ("ok", {"prompt_tokens": 1000, "completion_tokens": 100})
        self.assertEqual(ask_mod.ask("anthropic:claude-test-1-5", "s", "u")[1]["cost_estimated"], True)
        ask_mod.HOOK = lambda *a: ("ok", {"prompt_tokens": 1000, "completion_tokens": 100, "cost": 0.01})
        self.assertNotIn("cost_estimated", ask_mod.ask("anthropic:claude-test-1-5", "s", "u")[1])

    def test_turn_is_priced_once_on_summed_tokens(self):
        d = Path(self.tmp.name) / "r"
        d.mkdir()
        page = make_page(d)

        class Fake:
            via = "openai"
            truncated = False
            steps = [('<comment on="passage"><quote>physical truths</quote>x</comment><comment on="c999">y</comment>',
                      {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}),
                     ("done", {"prompt_tokens": 120, "completion_tokens": 5, "total_tokens": 125})]

            def step(self):
                return self.steps.pop(0)

            def say(self, text):
                pass

        real = rounds.open_session
        rounds.open_session = lambda *a, **k: Fake()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rounds.take_turn(page, {"name": "alef", "model": "openai:gpt-test"}, 3, lambda me: page.d["comments"],
                                 lambda a: a, "")
        finally:
            rounds.open_session = real
        u = page.d["log"][-1]["usage"]
        self.assertEqual((u["prompt_tokens"], u["completion_tokens"], u["cost_estimated"]), (220, 15, True))
        self.assertAlmostEqual(u["cost"], 220 * 2e-06 + 15 * 1e-05)

    def test_snapshot_file(self):
        listing = {"data": [
            {"id": "z/b", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
            {"id": "a/a", "pricing": {"prompt": "0.0000005", "completion": "0"}},
            {"id": "free/x", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}},
            {"id": "broken", "pricing": {}}]}
        real = prices_cmd.fetch
        prices_cmd.fetch = lambda: listing
        out = Path(self.tmp.name) / "p.json"
        try:
            run(["prices", "--out", str(out)])
        finally:
            prices_cmd.fetch = real
        text = out.read_text(encoding="utf-8")
        got = json.loads(text)
        self.assertEqual(got["source"], prices.SOURCE)
        self.assertEqual(got["models"], {"a/a": {"prompt": 5e-07, "completion": 0.0}, "z/b": {"prompt": 1e-06, "completion": 2e-06}})
        self.assertEqual(text.splitlines()[1:3], ['  "a/a": {"prompt": 5e-07, "completion": 0.0},',
                                                  '  "z/b": {"prompt": 1e-06, "completion": 2e-06}'])

    def test_checked_in_snapshot_parses(self):
        prices.TABLE = None
        snap = json.loads(prices.FILE.read_text(encoding="utf-8"))
        self.assertTrue(snap["fetched"] and snap["models"])
        self.assertEqual(list(snap["models"]), sorted(snap["models"]))
        self.assertTrue(all(v["prompt"] > 0 or v["completion"] > 0 for v in snap["models"].values()))


class Spend(unittest.TestCase):
    def setUp(self):
        prices.TABLE = dict(FAKE)
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        for name, started in (("early", "2026-01-01T00:00:00"), ("late", "2026-02-01T12:00:00")):
            d = self.base / name
            d.mkdir()
            page = make_page(d)
            page.d["started"] = started
            page.d["log"] = [
                {"layer": 1, "reader": "alef", "model": "openrouter:x/y", "usage": {"prompt_tokens": 5, "cost": 0.5}},
                # logged before costs were estimated: priced when read
                {"layer": 1, "reader": "bet", "model": "openai:gpt-test", "usage": {"prompt_tokens": 1000, "completion_tokens": 100}},
                {"layer": 2, "reader": "bet", "model": "openai:gpt-test", "usage": {"prompt_tokens": 1, "cost": 0.25, "cost_estimated": True}},
                {"layer": 2, "reader": "alef", "model": "mock:alef", "usage": {"prompt_tokens": 3}}]
            page.save()
            page.save_side("plants", {"plants": [], "usage": [{"cost": 1.0}, {"cost": 0.125, "cost_estimated": True}]})

    def tearDown(self):
        prices.TABLE = None
        self.tmp.cleanup()

    def test_table_splits_estimated_cost(self):
        r = runs(self.base)[0]
        self.assertEqual((r["cost"], r["cost_estimated"]), (1.878, 0.378))
        log = json.loads((self.base / "early" / "page.json").read_text(encoding="utf-8"))["log"]
        self.assertNotIn("cost", log[1]["usage"])  # the record is not rewritten

    def test_spend(self):
        out = run(["spend", "--runs", str(self.base)])
        lines = out.splitlines()
        self.assertTrue(any(l.startswith("early ") and l.split()[-3:] == ["1.5000", "0.3780", "1.8780"] for l in lines))
        self.assertEqual(lines[-1], "total 3.7560 USD")
        out = run(["spend", "--runs", str(self.base), "--since", "2026-02-01T12:00"])
        self.assertNotIn("early", out)
        self.assertEqual(out.splitlines()[-1], "total 1.8780 USD")
        self.assertEqual(run(["spend", "--runs", str(self.base), "--since", "2027-01-01"]).splitlines()[-1], "total 0.0000 USD")


if __name__ == "__main__":
    unittest.main()
