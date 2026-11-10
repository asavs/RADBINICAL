import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from radbinical import ask, forecast, rounds
from radbinical.cli import main
from radbinical.config import DEFAULT_FLAGS
from radbinical.page import Page, reader_entry

TEXT = "The laws of production are fixed. Distribution is a matter of human institution solely. A third sentence of some length here."
READERS = ("mock:alef", "mock:bet", "mock:gimel")
REAL_OPEN = rounds.open_session


def new_page(tmp, **flags):
    data = {"passage": {"id": "t", "title": "T", "source": "", "text": TEXT},
            "readers": [reader_entry(m) for m in READERS],
            "flags": {**DEFAULT_FLAGS, "seed": 3, **flags}, "comments": [], "log": [], "counter": 0, "layers_done": 0}
    return Page(data, tmp)


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


def first_two_ids(model, system, user, max_tokens, temperature):
    """Forecast answer naming the first two comments in the margins."""
    ids = re.findall(r"^\s*\[(c\d+)\]", user, re.M)[:2]
    return json.dumps({"expect": ids, "probabilities": {i: 0.5 for i in ids}}), {"via": "hook", "cost": 0.001}


def strip_usage(log):
    return [{k: v for k, v in e.items() if k != "usage"} for e in log]


class Scoring(unittest.TestCase):
    def comments(self):
        c = lambda i, a, layer, target: {"id": f"c{i}", "n": i, "author": a, "layer": layer, "target": target, "text": "x"}
        return [c(1, "alef", 1, "passage"), c(2, "bet", 1, "passage"), c(3, "gimel", 1, "passage"),
                c(4, "bet", 2, "c1"),     # reply from another reader: counts for c1
                c(5, "alef", 2, "c1"),    # c1's author replying to itself: does not count
                c(6, "alef", 2, "c2"),    # the forecaster's own reply: counts, marked by_forecaster
                c(7, "gimel", 2, "c3"),   # self-reply only: c3 drew no reply
                c(8, "bet", 1, "c3")]     # an earlier round's reply: not this round's

    def test_constructed_case(self):
        f = forecast.score({"round": 2, "reader": "alef", "predicted": ["c1", "c3"], "seen": ["c1", "c2", "c3", "c8"]},
                           self.comments())
        self.assertEqual(f["replied"], ["c1", "c2"])
        self.assertEqual(f["hits"], ["c1"])
        self.assertEqual(f["by_forecaster"], ["c2"])
        self.assertEqual((f["precision"], f["recall"], f["chance"]), (0.5, 0.5, 0.5))

    def test_replies_already_seen_do_not_count(self):
        f = forecast.score({"round": 2, "reader": "gimel", "predicted": ["c1"], "seen": ["c1", "c2", "c3", "c4"]},
                           self.comments())
        self.assertEqual(f["replied"], ["c2"])
        self.assertEqual((f["hits"], f["precision"], f["recall"], f["chance"]), ([], 0.0, 0.0, 0.25))

    def test_empty_forecast_has_no_precision(self):
        f = forecast.score({"round": 2, "reader": "alef", "predicted": [], "seen": ["c1", "c2", "c3"]}, self.comments())
        self.assertIsNone(f["precision"])
        self.assertAlmostEqual(f["chance"], 0.6667)

    def test_parse(self):
        known = {"c1", "c2", "c3"}
        self.assertEqual(forecast.parse({"expect": ["c1", "[c2]", "c9"], "probabilities": {"c1": 0.7, "c2": 3}}, known),
                         (["c1", "c2"], {"c1": 0.7}, ["c9"]))
        self.assertEqual(forecast.parse([{"id": "c3", "p": 0.2}, "c1"], known), (["c3", "c1"], {"c3": 0.2}, []))
        with self.assertRaises(ValueError):
            forecast.parse({"answer": "c1"}, known)


class InTheRoundLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []

    def tearDown(self):
        ask.HOOK = None
        rounds.open_session = REAL_OPEN
        self.tmp.cleanup()

    def run_page(self, name, layers=3, **flags):
        d = Path(self.tmp.name) / name
        d.mkdir()
        page = new_page(d, stop_when_all_pass=False, **flags)
        quiet(rounds.run_layers, page, layers)
        return page

    def test_flag_off_makes_no_calls_and_no_side_file(self):
        ask.HOOK = lambda *a: self.calls.append(a) or ("{}", {})
        page = self.run_page("off")
        self.assertEqual(self.calls, [])
        self.assertIsNone(page.side("forecasts"))

    def test_flag_on_leaves_the_annotations_unchanged(self):
        off = self.run_page("off")
        ask.HOOK = first_two_ids
        on = self.run_page("on", forecast=True)
        self.assertEqual(on.d["comments"], off.d["comments"])
        self.assertEqual(strip_usage(on.d["log"]), strip_usage(off.d["log"]))

    def test_forecast_sees_exactly_the_turns_page(self):
        turns, asked = {}, {}

        def spy(reader, system, user, flags, **k):
            turns[(user.split(".")[0], reader["name"])] = user
            return REAL_OPEN(reader, system, user, flags, **k)

        def hook(model, system, user, *rest):
            asked[(user.split(".")[0], model.split(":")[1])] = user
            return first_two_ids(model, system, user, *rest)
        rounds.open_session, ask.HOOK = spy, hook
        for sequential in (False, True):
            turns.clear(), asked.clear()
            self.run_page(f"same-{sequential}", forecast=True, sequential=sequential)
            self.assertEqual(sorted(asked), sorted(k for k in turns if k[0] != "Round 1"))
            for k, user in asked.items():
                self.assertTrue(user.startswith(turns[k]))
                self.assertTrue(user[len(turns[k]):].startswith("\n\n=== THE QUESTION ==="))

    def test_flag_on_writes_scored_forecasts(self):
        ask.HOOK = first_two_ids
        page = self.run_page("on", forecast=True)
        side = page.side("forecasts")
        fs = side["forecasts"]
        self.assertEqual(sorted((f["round"], f["reader"]) for f in fs),
                         sorted((r, n) for r in (2, 3) for n in ("alef", "bet", "gimel")))
        self.assertEqual(len(side["usage"]), 6)
        for f in fs:
            self.assertNotIn("error", f)
            self.assertEqual(len(f["predicted"]), min(2, len(f["seen"])))
            self.assertTrue(set(f["predicted"]) <= set(f["seen"]))
            again = forecast.score({k: f[k] for k in ("round", "reader", "predicted", "seen")}, page.d["comments"])
            self.assertEqual({k: f[k] for k in again}, again)

    def test_failed_forecast_does_not_sink_the_round(self):
        off = self.run_page("off")

        def hook(model, system, user, *rest):
            if model == "mock:alef":
                raise RuntimeError("provider down")
            if model == "mock:bet":
                return "I would rather not say.", {}
            return first_two_ids(model, system, user, *rest)
        ask.HOOK = hook
        on = self.run_page("on", forecast=True)
        self.assertEqual(on.d["layers_done"], 3)
        self.assertEqual(on.d["comments"], off.d["comments"])
        fs = {(f["round"], f["reader"]): f for f in on.side("forecasts")["forecasts"]}
        self.assertIn("provider down", fs[(2, "alef")]["error"])
        self.assertIn("ValueError", fs[(2, "bet")]["error"])
        self.assertNotIn("error", fs[(2, "gimel")])
        self.assertNotIn("precision", fs[(2, "alef")])

    def test_forecast_command_reports_and_rescores(self):
        ask.HOOK = first_two_ids
        page = self.run_page("on", forecast=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["forecast", str(page.dir), "--rescore"])
        text = out.getvalue()
        self.assertIn("6 forecasts", text)
        for name in ("alef", "bet", "gimel", "pooled", "chance"):
            self.assertIn(name, text)

    def test_forecast_command_without_forecasts_exits(self):
        page = self.run_page("off", layers=1)
        with self.assertRaises(SystemExit):
            quiet(main, ["forecast", str(page.dir)])


class Summary(unittest.TestCase):
    def test_grouping(self):
        fs = [{"round": 2, "reader": "a", "predicted": ["c1", "c2"], "hits": ["c1"], "replied": ["c1"], "by_forecaster": [],
               "precision": 0.5, "recall": 1.0, "chance": 0.25},
              {"round": 3, "reader": "a", "predicted": ["c1"], "hits": ["c1"], "replied": ["c1", "c3"], "by_forecaster": ["c1"],
               "precision": 1.0, "recall": 0.5, "chance": 0.5},
              {"round": 3, "reader": "b", "error": "x"}]
        s = forecast.summary(fs, "reader")
        self.assertEqual((s["a"]["named"], s["a"]["hits"], s["a"]["self"], s["a"]["pooled_precision"]), (3, 2, 1, 0.6667))
        self.assertEqual((s["a"]["precision"], s["a"]["recall"], s["a"]["chance"]), (0.75, 0.75, 0.375))
        self.assertEqual((s["b"]["forecasts"], s["b"]["errors"], s["b"]["precision"]), (1, 1, None))
        self.assertEqual(sorted(forecast.summary(fs, "round")), [2, 3])
