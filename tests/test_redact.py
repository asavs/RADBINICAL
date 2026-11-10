import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical import ask as ask_mod
from radbinical.cli import main
from radbinical.config import DEFAULT_FLAGS
from radbinical.page import Page, reader_entry
from radbinical.redact import compare, jaccard, judge_items, judge_prompt, mechanical, page_text, parse_items, redact

TEXT = "The laws of production are fixed. Distribution is a matter of human institution solely."


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


def make_page(tmp, signed=True):
    data = {"passage": {"title": "T", "source": "", "text": TEXT},
            "readers": [reader_entry(m) for m in ("mock:alef", "mock:bet")],
            "flags": {**DEFAULT_FLAGS, "signed": signed}, "comments": [], "log": [], "counter": 0, "layers_done": 2}
    page = Page(data, tmp)
    page.add("alef", 1, {"target": "passage", "quote": "laws of production", "text": "Production is “not fixed” at all."})
    page.add("bet", 1, {"target": "passage", "quote": "human institution", "text": "Institutions are themselves constrained."})
    page.add("bet", 2, {"target": "c1", "text": "I disagree: technique fixes output."})
    page.add("alef", 2, {"target": "c2", "text": "Granted, I withdraw that.",},
             kind="plant", meta={"truth": "SECRET-TRUTH"})
    page.save()
    return page


def item(status="disputed", cites=("c1", "c3"), quotes=(("c1", "not fixed"),), summary="Alef and Bet disagree."):
    return {"status": status, "summary": summary, "cites": list(cites), "quotes": [{"id": i, "text": t} for i, t in quotes]}


class Hook:
    """Stands in for every model: answers by model id, records what each was sent."""

    def __init__(self, answers):
        self.answers, self.seen = answers, []

    def __call__(self, model, system, user, max_tokens, temperature):
        self.seen.append((model, system, user))
        a = self.answers[model]
        if isinstance(a, Exception):
            raise a
        return (a(user) if callable(a) else a), {"cost": 0.001, "via": "test"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.page = make_page(self.tmp.name)

    def tearDown(self):
        ask_mod.HOOK = None
        self.tmp.cleanup()

    def hook(self, answers):
        ask_mod.HOOK = Hook(answers)
        return ask_mod.HOOK

    def side(self):
        return json.loads((Path(self.tmp.name) / "redactions.json").read_text(encoding="utf-8"))


class Parsing(unittest.TestCase):
    def test_valid_and_normalised(self):
        items, notes = parse_items({"items": [{"status": " Settled ", "summary": " s ", "cites": ["[c2]", 4, "c2"],
                                               "quotes": [{"id": "c4", "text": " Granted "}]}]})
        self.assertEqual(items, [{"status": "settled", "summary": "s", "cites": ["c2", "c4"], "quotes": [{"id": "c4", "text": "Granted"}]}])
        self.assertEqual(notes, [])

    def test_bare_list_and_other_key(self):
        self.assertEqual(len(parse_items([item()])[0]), 1)
        self.assertEqual(len(parse_items({"report": [item()]})[0]), 1)
        self.assertEqual(parse_items({"status": "settled", "summary": "x", "cites": "c1, c2"})[0][0]["cites"], ["c1", "c2"])

    def test_bad_items_dropped_with_notes(self):
        raw = [item(), "junk", {**item(), "status": "decided"}, {**item(), "summary": ""}, {**item(), "cites": []},
               {**item(), "quotes": [{"id": "c1"}, "x"]}]
        items, notes = parse_items(raw)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1]["quotes"], [])
        self.assertEqual(len(notes), 6)

    def test_no_list_raises(self):
        with self.assertRaises(ValueError):
            parse_items({"verdict": "none"})


class Mechanical(Base):
    def by_id(self):
        return {c["id"]: c for c in self.page.d["comments"]}

    def test_all_good_and_tolerant_quote(self):
        it = parse_items([item(quotes=(("c1", '"NOT   fixed"'), ("c3", "technique fixes output.")))])[0][0]
        self.assertEqual(mechanical(it, self.by_id()), {"ids_ok": True, "missing": [], "quotes_ok": True, "unfound": []})

    def test_missing_id(self):
        chk = mechanical(item(cites=("c1", "c9")), self.by_id())
        self.assertEqual((chk["ids_ok"], chk["missing"]), (False, ["c9"]))

    def test_unfound_quote(self):
        it = item(quotes=(("c1", "not fixed"), ("c2", "not fixed"), ("c7", "x y")))
        chk = mechanical(it, self.by_id())
        self.assertFalse(chk["quotes_ok"])
        self.assertEqual([q["id"] for q in chk["unfound"]], ["c2", "c7"])


class Compare(unittest.TestCase):
    def test_jaccard(self):
        self.assertEqual(jaccard({"a", "b"}, {"b", "c"}), 0.333)
        self.assertIsNone(jaccard(set(), set()))
        self.assertEqual(jaccard({"a"}, set()), 0.0)

    def test_arithmetic(self):
        reds = [
            {"model": "x", "items": [item("disputed", ["c1", "c2"]), item("settled", ["c3"])]},
            {"model": "y", "items": [item("disputed", ["c1"]), item("unresolved", ["c3", "c9"])]},
            {"model": "z", "items": [item("disputed", ["c1", "c4"])]},
            {"model": "broken", "error": "boom", "items": []},
        ]
        c = compare(reds, ["c1", "c2", "c3", "c4", "c5"])
        self.assertEqual(c["models"], ["x", "y", "z"])
        xy = c["pairs"][0]
        self.assertEqual((xy["a"], xy["b"], xy["all"], xy["disputed"], xy["settled"], xy["unresolved"]),
                         ("x", "y", 0.667, 0.5, 0.0, 0.0))
        xz = c["pairs"][1]
        self.assertEqual((xz["all"], xz["disputed"], xz["settled"], xz["unresolved"]), (0.25, 0.333, 0.0, None))
        self.assertEqual(c["core"], ["c1"])
        self.assertEqual(c["only_one"], {"c2": "x", "c4": "z"})
        self.assertEqual(c["uncited"], 0.2)

    def test_nothing(self):
        c = compare([], ["c1"])
        self.assertEqual((c["pairs"], c["core"], c["only_one"], c["uncited"]), ([], [], {}, 1.0))


class Redacting(Base):
    def test_concurrent_models_checks_and_usage(self):
        good = json.dumps({"items": [item(), item("settled", ["c2", "c4"], [("c4", "I withdraw")]),
                                     item("unresolved", ["c9"], [("c3", "not here")]), {"status": "?"}]})
        self.hook({"m:a": good, "m:b": "Sure: " + json.dumps([item("disputed", ["c1"])])})
        side = redact(self.page, ["m:a", "m:b"])
        a, b = side["redactions"]
        self.assertEqual((a["model"], a["name"], b["name"]), ("m:a", "m:a", "m:b"))
        self.assertEqual(len(a["items"]), 3)
        self.assertEqual(len(a["notes"]), 1)
        self.assertEqual([it["check"]["ids_ok"] for it in a["items"]], [True, True, False])
        self.assertEqual([it["check"]["quotes_ok"] for it in a["items"]], [True, True, False])
        self.assertNotIn("verdict", a["items"][0]["check"])
        self.assertEqual(len(side["usage"]), 2)
        self.assertEqual(side["compare"]["core"], ["c1"])
        self.assertEqual(self.side(), side)

    def test_rerun_replaces_that_model_only(self):
        self.hook({"m:a": json.dumps([item()]), "m:b": json.dumps([item()])})
        redact(self.page, ["m:a", "m:b"])
        self.hook({"m:a": json.dumps([item("settled", ["c2"]), item("settled", ["c4"])])})
        side = redact(self.page, ["m:a"])
        self.assertEqual([r["model"] for r in side["redactions"]], ["m:b", "m:a"])
        self.assertEqual(len(side["redactions"][1]["items"]), 2)
        self.assertEqual(len(side["usage"]), 3)

    def test_failures_are_recorded_not_raised(self):
        self.hook({"m:a": "no json here", "m:b": RuntimeError("down"), "m:c": json.dumps({"verdict": 1}),
                   "m:d": json.dumps([item()])})
        side = redact(self.page, ["m:a", "m:b", "m:c", "m:d"])
        errs = {r["model"]: r.get("error", "") for r in side["redactions"]}
        self.assertIn("ValueError", errs["m:a"])
        self.assertIn("down", errs["m:b"])
        self.assertIn("no list", errs["m:c"])
        self.assertEqual(errs["m:d"], "")
        self.assertEqual(side["compare"]["models"], ["m:d"])

    def test_kind_and_meta_hidden_and_labels(self):
        h = self.hook({"m:a": "[]"})
        redact(self.page, ["m:a"])
        system, user = h.seen[0][1], h.seen[0][2]
        self.assertNotIn("SECRET-TRUTH", user)
        self.assertNotIn("plant", user + system)
        self.assertIn("[c4] alef", user)
        self.assertIn("decide nothing", system)
        redact(self.page, ["m:a"], signed=False)
        self.assertIn("[c4] Reader A", h.seen[1][2])
        self.assertNotIn("alef", h.seen[1][2])
        self.assertFalse(self.side()["redactions"][0]["signed"])

    def test_page_flag_sets_labels(self):
        page = make_page(self.tmp.name, signed=False)
        self.assertIn("Reader B", page_text(page.d, False))
        h = self.hook({"m:a": "[]"})
        redact(page, ["m:a"])
        self.assertIn("Reader B", h.seen[0][2])

    def test_plain_mock_model_is_an_error_not_a_crash(self):
        side = redact(self.page, ["mock:r"])
        self.assertIn("no JSON", side["redactions"][0]["error"])
        self.assertEqual(side["usage"], [{"via": "mock"}])


class Judging(Base):
    def test_prompt_has_cited_comments_and_parents_only(self):
        p = judge_prompt(item(cites=("c4", "c9")), self.page.d, True)
        self.assertIn("[c4] alef", p)
        self.assertIn("[c2] (context", p)
        self.assertIn("[c9] (no such comment", p)
        self.assertNotIn("[c1]", p)
        self.assertNotIn("SECRET", p)

    def test_verdicts_stored(self):
        self.hook({"m:a": json.dumps([item(), item("settled", ["c4"]), item("unresolved", ["c2"])])})
        redact(self.page, ["m:a"])
        def judge(user):
            if "STATUS: disputed" in user:
                return '{"verdict": "Supported", "why": "matches\\n c1 and c3"}'
            if "STATUS: settled" in user:
                return '{"verdict": "distorted", "why": "c4 is not a withdrawal by c2\'s author"}'
            return "I cannot say."
        self.hook({"j": judge})
        side = judge_items(self.page, "j")
        checks = [it["check"] for it in side["redactions"][0]["items"]]
        self.assertEqual([c["verdict"] for c in checks], ["supported", "distorted", None])
        self.assertEqual(checks[0]["why"], "matches c1 and c3")
        self.assertEqual(checks[0]["judge"], "j")
        self.assertTrue(checks[0]["ids_ok"])
        self.assertEqual(len(side["usage"]), 3)
        self.assertEqual(self.side(), side)


class Command(Base):
    def test_cli_forms(self):
        self.hook({"m:a": json.dumps([item()]), "m:b": json.dumps([item(cites=["c1"])]),
                   "j": '{"verdict": "supported", "why": "ok"}'})
        run = self.tmp.name
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["redact", run, "--models", "m:a, m:b", "--unsigned"])
            main(["redact", "check", run, "--judge", "j"])
            main(["redact", "compare", run])
        side = self.side()
        self.assertEqual([r["model"] for r in side["redactions"]], ["m:a", "m:b"])
        self.assertTrue(all(it["check"]["verdict"] == "supported" for r in side["redactions"] for it in r["items"]))
        self.assertEqual(side["compare"]["pairs"][0]["all"], 0.5)
        self.assertIn("supported 1", out.getvalue())
        self.assertIn("cited by every redaction: c1", out.getvalue())

    def test_cli_needs_its_options(self):
        for argv in (["redact", self.tmp.name], ["redact", "check", self.tmp.name, "--judge", "j"],
                     ["redact", "check", self.tmp.name], ["redact", "check"]):
            with self.assertRaises(SystemExit):
                quiet(main, argv)

    def test_all_models_failing_exits_nonzero(self):
        self.hook({"m:a": "nope"})
        with self.assertRaises(SystemExit) as e:
            quiet(main, ["redact", self.tmp.name, "--models", "m:a"])
        self.assertEqual(e.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
