import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical import ask, caselaw
from radbinical.cli import main
from radbinical.config import DEFAULT_FLAGS, ROOT
from radbinical.page import Page, reader_entry

TEXT = "The laws of production are fixed. Distribution is a matter of human institution solely."
CASES = [{"id": "k1", "case": "A case.", "question": "P or Q?", "options": ["P", "Q"]},
         {"id": "k2", "case": "Another.", "question": "P or Q?", "options": ["P", "Q"]}]


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


def ruling(case, name, cond, rep, option, cites=(), error=None):
    r = {"case": case, "model": f"mock:{name}", "name": name, "condition": cond, "rep": rep,
         "option": option, "reason": "", "cites": list(cites)}
    if error:
        r["error"] = error
    return r


class CasesFiles(unittest.TestCase):
    def test_shipped_cases_load(self):
        for pid in ("mill-property", "hume-equality"):
            cases = caselaw.load_cases(ROOT / "cases" / f"{pid}.json")
            self.assertEqual(len(cases), 6)
            self.assertTrue((ROOT / "passages" / f"{pid}.txt").exists())
            for c in cases:
                self.assertEqual(len(c["options"]), 2)
                self.assertTrue(c["case"] and c["question"])

    def test_bad_cases_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "c.json"
            for bad in ([], [{"id": "a", "case": "x", "question": "y", "options": ["only one"]}],
                        [{"id": "a", "case": "x", "options": ["p", "q"]}],
                        [{"id": "a", "case": "x", "question": "y", "options": ["p", "q"]}] * 2):
                f.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaises(ValueError):
                    caselaw.load_cases(f)


class Validation(unittest.TestCase):
    OPTS = ["Distribution: the levy disposes of things once there", "Production: it runs into the laws"]

    def test_pick_option(self):
        o = self.OPTS
        for raw, want in (("A", o[0]), ("b.", o[1]), ("(B)", o[1]), (2, o[1]), ("production: IT runs into the laws.", o[1]),
                          ("B. Production: it runs into the laws", o[1]), ("C", None), (3, None), ("neither", None),
                          (None, None), (True, None)):
            self.assertEqual(caselaw.pick_option(raw, o), want, raw)

    def test_invalid_option_is_an_error(self):
        case = {"id": "k", "options": self.OPTS}
        r, err = caselaw.validate({"option": "maybe", "reason": "r"}, case, "page", {"c1"})
        self.assertIsNone(r["option"])
        self.assertIn("not one of the options", err)
        r, err = caselaw.validate(["A"], case, "page", {"c1"})
        self.assertIsNotNone(err)

    def test_unknown_cites_are_dropped(self):
        case = {"id": "k", "options": self.OPTS}
        r, err = caselaw.validate({"option": "A", "cites": ["c1", "[c2]", "c99", "c1"]}, case, "page", {"c1", "c2"})
        self.assertIsNone(err)
        self.assertEqual((r["cites"], r["bad_cites"]), (["c1", "c2"], ["c99"]))
        r, _ = caselaw.validate({"option": "A", "cites": "c1, c2"}, case, "bare", {"c1", "c2"})
        self.assertEqual((r["cites"], r["bad_cites"]), ([], ["c1", "c2"]))


class Arithmetic(unittest.TestCase):
    def setUp(self):
        R = ruling
        self.rulings = [
            # bare, k1: x P P, y P Q (tie -> P), z Q Q
            R("k1", "x", "bare", 0, "P"), R("k1", "x", "bare", 1, "P"),
            R("k1", "y", "bare", 0, "P"), R("k1", "y", "bare", 1, "Q"),
            R("k1", "z", "bare", 0, "Q"), R("k1", "z", "bare", 1, "Q"),
            # bare, k2: everyone P
            *[R("k2", n, "bare", k, "P") for n in "xyz" for k in (0, 1)],
            # page, k1: everyone P; x and y cite
            R("k1", "x", "page", 0, "P", ["c1"]), R("k1", "x", "page", 1, "P", ["c1"]),
            R("k1", "y", "page", 0, "P", ["c1", "c2"]), R("k1", "y", "page", 1, "P", ["c2", "c1"]),
            R("k1", "z", "page", 0, "P"), R("k1", "z", "page", 1, "P"),
            # page, k2: x Q Q, y P P, z P and one error
            R("k2", "x", "page", 0, "Q"), R("k2", "x", "page", 1, "Q"),
            R("k2", "y", "page", 0, "P"), R("k2", "y", "page", 1, "P"),
            R("k2", "z", "page", 0, "P"), R("k2", "z", "page", 1, None, error="bad"),
        ]
        self.s = caselaw.summarize(CASES, self.rulings)

    def test_bare(self):
        b = self.s["conditions"]["bare"]
        self.assertEqual(b["per_case"]["k1"], {"models": 3, "counts": {"P": 2, "Q": 1}, "agreement": 0.6667, "pairwise": 0.3333})
        self.assertEqual((b["per_case"]["k2"]["agreement"], b["per_case"]["k2"]["pairwise"]), (1.0, 1.0))
        self.assertEqual((b["agreement"], b["pairwise"], b["self_consistency"]), (0.8333, 0.6667, 0.9167))
        self.assertEqual((b["rulings"], b["errors"]), (12, 0))

    def test_page(self):
        p = self.s["conditions"]["page"]
        self.assertEqual((p["per_case"]["k1"]["agreement"], p["per_case"]["k2"]["agreement"]), (1.0, 0.6667))
        self.assertEqual((p["agreement"], p["pairwise"]), (0.8333, 0.6667))
        self.assertEqual(p["self_consistency"], 1.0)   # z's single valid rep on k2 does not count
        self.assertEqual((p["rulings"], p["errors"], p["valid"], p["citing"]), (12, 1, 11, 4))
        self.assertEqual(p["precedents"], [["c1", 4], ["c2", 2]])

    def test_changed(self):
        ch = self.s["changed"]
        self.assertEqual((ch["count"], ch["of"]), (2, 6))
        self.assertEqual(sorted((w["case"], w["name"], w["bare"], w["page"]) for w in ch["which"]),
                         [("k1", "z", "Q", "P"), ("k2", "x", "P", "Q")])

    def test_single_model_has_no_pairwise(self):
        s = caselaw.summarize(CASES, [ruling("k1", "x", "bare", 0, "P")])
        self.assertIsNone(s["conditions"]["bare"]["pairwise"])
        self.assertEqual(s["conditions"]["bare"]["agreement"], 1.0)
        self.assertIsNone(s["conditions"]["bare"]["self_consistency"])

    def test_report_says_consistent_not_correct(self):
        text = caselaw.report(CASES, self.s, 2)
        self.assertIn("more consistent", text)
        self.assertIn("not more correct", text)
        self.assertIn("self-consistency", text)


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name) / "run"
        d.mkdir()
        data = {"passage": {"id": "t", "title": "T", "source": "", "text": TEXT},
                "readers": [reader_entry(m) for m in ("mock:alef", "mock:bet")],
                "flags": dict(DEFAULT_FLAGS), "comments": [], "log": [], "counter": 0, "layers_done": 1}
        self.page = Page(data, d)
        self.page.add("alef", 1, {"target": "passage", "quote": "laws of production", "text": "gloss"})
        self.page.add("bet", 1, {"target": "c1", "text": "reply"})
        self.page.save()
        self.cases = Path(self.tmp.name) / "cases.json"
        self.cases.write_text(json.dumps(CASES), encoding="utf-8")
        self.seen = []

    def tearDown(self):
        ask.HOOK = None
        self.tmp.cleanup()

    def hook(self, model, system, user, max_tokens, temperature):
        self.seen.append(user)
        page = "=== THE MARGINS" in user
        if model == "mock:junk":
            return "no JSON here", {"via": "hook"}
        if model == "mock:wrong":
            return '{"option": "Z", "reason": "?"}', {"via": "hook"}
        return json.dumps({"option": "B" if page else "A", "reason": "because", "cites": ["c2", "c40"] if page else []}), {"via": "hook"}

    def test_end_to_end(self):
        ask.HOOK = self.hook
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["caselaw", str(self.page.dir), "--cases", str(self.cases), "--models", "mock:a,mock:b,mock:junk,mock:wrong",
                  "--repeat", "2", "--workers", "3"])
        side = self.page.side("rulings")
        self.assertEqual(set(side), {"cases", "rulings", "summary", "usage"})
        self.assertEqual(len(side["rulings"]), 2 * 4 * 2 * 2)
        self.assertEqual(len(side["usage"]), 2 * 4 * 2 * 2)   # unusable answers still cost
        rs = side["rulings"]
        for r in rs:
            self.assertEqual(set(r) - {"error", "bad_cites"}, {"case", "model", "name", "condition", "rep", "option", "reason", "cites"})
        good = [r for r in rs if r["name"] in ("a", "b")]
        self.assertTrue(all(not r.get("error") for r in good))
        self.assertTrue(all(r["cites"] == ["c2"] and r["bad_cites"] == ["c40"] for r in good if r["condition"] == "page"))
        self.assertTrue(all(r.get("error") and r["option"] is None for r in rs if r["name"] in ("junk", "wrong")))
        s = side["summary"]
        self.assertEqual(s["changed"]["count"], 4)
        self.assertEqual(s["conditions"]["page"]["precedents"], [["c2", 8]])
        self.assertEqual(s["conditions"]["bare"]["self_consistency"], 1.0)
        self.assertIn("not more correct", out.getvalue())
        bare = [u for u in self.seen if "=== THE MARGINS" not in u]
        self.assertTrue(bare and all("gloss" not in u for u in bare))

    def test_report_mode_makes_no_calls(self):
        ask.HOOK = self.hook
        quiet(main, ["caselaw", str(self.page.dir), "--cases", str(self.cases), "--models", "mock:a"])
        n = len(self.seen)
        quiet(main, ["caselaw", str(self.page.dir), "--report"])
        self.assertEqual(len(self.seen), n)

    def test_missing_cases_file_exits(self):
        with self.assertRaises(SystemExit):
            quiet(main, ["caselaw", str(self.page.dir)])
