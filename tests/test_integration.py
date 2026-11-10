"""Where the instruments meet: people on pages that are amended, ruled on and forked; forks in the
readings; the side files as the viewer reads them; the site built from any folder of runs."""
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from radbinical import amend, ask, human
from radbinical.cli import main
from radbinical.commands.fork import fork
from radbinical.commands.plant import add_plant
from radbinical.config import TEMPLATES
from radbinical.judge import summarise_plant
from radbinical.page import Page, labeller, models_of, reader_entry
from radbinical.readings import presence, readings
from radbinical.rounds import run_layers
from radbinical.table import rows

from test_human import make_run, sub
from test_readings import gloss, make_page


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return f(*a, **k)


class Recorder:
    """ask.HOOK that records the models asked and answers MOCK_REPLY lines, or with {}."""

    def __init__(self, answer="{}"):
        self.models, self.answer = [], answer

    def __call__(self, model, system, user, max_tokens, temperature):
        self.models.append(model)
        m = re.search(r"^MOCK_REPLY:[ \t]*(.*)$", user, re.M)
        return (m.group(1) if m else self.answer), {"via": "hook"}


class People(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        ask.HOOK = None
        self.tmp.cleanup()

    def with_person(self):
        run = self.root / "runs" / "r1"
        make_run(run)
        errs, ids = human.add(run, sub(), "ruth.json")
        self.assertEqual((errs, len(ids)), ([], 1))
        return run

    def test_caselaw_asks_only_models(self):
        run = self.with_person()
        cases = self.root / "cases.json"
        cases.write_text(json.dumps([{"id": "k", "case": "c", "question": "q", "options": ["x", "y"]}]), encoding="utf-8")
        ask.HOOK = rec = Recorder('{"option": "A", "reason": "r"}')
        quiet(main, ["caselaw", str(run), "--cases", str(cases)])
        self.assertEqual(sorted(set(rec.models)), ["mock:alef", "mock:bet"])
        names = {r["name"] for r in Page.load(run).side("rulings")["rulings"]}
        self.assertEqual(names, {"alef", "bet"})

    def test_amendment_asks_only_models_and_counts_them(self):
        cfg = {"question": "Should courts publish dissents?", "models": ["mock:alef", "mock:bet", "mock:gimel"],
               "flags": {"seed": 1}}
        out = self.root / "runs" / "court"
        page = quiet(amend.start, cfg, out)
        quiet(run_layers, page, 1)
        self.assertEqual(human.add(out, sub(comments=[{"target": "passage", "quote": "The question asks", "text": "x"}]),
                                   "ruth.json")[0], [])
        page = Page.load(out)
        ask.HOOK = rec = Recorder()
        quiet(amend.cycle, page, 0)
        self.assertTrue(rec.models)
        self.assertFalse([m for m in rec.models if m.startswith("human:")])
        closed = [p for p in page.side("amendments")["proposals"] if p["status"] == "closed"]
        self.assertTrue(closed)
        for p in closed:  # a quorum is half the model readers: the person neither votes nor counts
            self.assertEqual(p["passed"], amend.tally(p["votes"], 3, 0.66)[3])

    def test_plants_go_under_model_names_only(self):
        run = self.with_person()
        page = Page.load(run)
        ok, msg = add_plant(page, {"as": "Ruth", "sort": "slip", "target": "c1", "text": "x", "truth": "y"})
        self.assertFalse(ok)
        self.assertIn("no model reader named 'Ruth'", msg)

    def test_letters_do_not_move_when_people_and_models_join(self):
        run = self.with_person()
        d = Page.load(run).d
        d["flags"]["signed"] = False
        before = labeller(d)
        d["readers"].append(reader_entry("mock:gimel"))
        after = labeller(d)
        self.assertEqual([before(n) for n in ("alef", "bet", "Ruth")], ["Reader A", "Reader B", "Reader C"])
        self.assertEqual([after(n) for n in ("alef", "bet", "Ruth", "gimel")], ["Reader A", "Reader B", "Reader C", "Reader D"])
        self.assertEqual([r["name"] for r in models_of(d)], ["alef", "bet", "gimel"])

    def test_a_fork_keeps_people_and_plants(self):
        run = self.with_person()
        page = Page.load(run)
        self.assertTrue(add_plant(page, {"as": "alef", "sort": "slip", "target": "c1", "text": "x", "truth": "y"})[0])
        page.save()
        [(copy, ok)] = quiet(fork, run, 1, rounds=1)
        kinds = [c.get("kind") for c in copy.d["comments"]]
        self.assertEqual((kinds.count("human"), kinds.count("plant")), (1, 1))
        self.assertTrue(any(r.get("human") for r in copy.d["readers"]))
        self.assertFalse(any(e["model"].startswith("human:") for e in copy.d["log"] if "from" not in e))


class ForksInReadings(unittest.TestCase):
    def test_copied_glosses_are_not_counted_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "runs"
            base.mkdir()
            src = make_page(base, "mill", "mill")
            gloss(src, "alef", 1, "laws of production", "production laws are physical truths fixed by nature")
            gloss(src, "bet", 1, "human institution", "distribution is a matter of choice and custom")
            src.d["layers_done"] = 1
            src.save()
            quiet(fork, base / "mill", 1)
            copy = Page.load(base / "mill-s1")
            gloss(copy, "alef", 2, "laws of production", "production laws are physical truths fixed by nature indeed")
            copy.add("bet", 2, {"target": "c1", "text": "a reply in the fork"})
            copy.save()
            rd, ms = readings(rows(base), "mock:bow", cache_dir=Path(tmp) / "emb")
            inherited = [m for m in ms if m.get("inherited")]
            self.assertEqual(sorted((m["run"], m["id"]) for m in inherited), [("mill-s1", "c1"), ("mill-s1", "c2")])
            own = {(m["run"], m["id"]): m["reading"] for m in ms if not m.get("inherited")}
            self.assertNotIn(("mill-s1", "c1"), own)
            for m in inherited:
                self.assertEqual(m["reading"], own[("mill", m["id"])])
            physical = next(r for r in rd if r["id"] == own[("mill", "c1")])
            self.assertEqual(physical["size"], 2)                 # the source's gloss and the fork's new one
            self.assertEqual(physical["runs"], ["mill", "mill-s1"])
            self.assertEqual(physical["direct_replies"], 1)       # the fork's reply to its copy of c1
            self.assertEqual(presence(ms, "run")["mill-s1"], {own[("mill-s1", "c3")]})


class ViewerReadsTheSideFiles(unittest.TestCase):
    """The viewer is a template, so these check that it reads the fields the writers write."""

    def setUp(self):
        self.tpl = (TEMPLATES / "viewer.html").read_text(encoding="utf-8")

    def test_plants(self):
        sound = summarise_plant({"id": "c3", "author": "a", "layer": 1, "meta": {"sort": "sound", "truth": "t"}},
                                [{"id": "c4", "author": "b", "round": 2, "verdict": "dismisses", "why": ""}])
        self.assertEqual((sound["caught"], sound["dismissed"], sound["dismissed_by"]), (False, True, ["b"]))
        for key in ("dismissed", "dismissed_by", "dismissed_round", "caught", "caught_round", "counts", "notes"):
            self.assertIn(key, self.tpl)

    def test_redactions_rulings_amendments_forecasts(self):
        for key in ("r.error", "r.notes", "r.signed", "C.pairs", "C.uncited", "C.core",
                    "S2.conditions", "ch.count", "p.status", "p.note", "f.error"):
            self.assertIn(key, self.tpl)


class SiteFromAnyFolder(unittest.TestCase):
    def test_runs_and_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp) / "runs"
            make_run(runs / "r1")
            make_run(runs / "r2")
            (runs / "not-a-run").mkdir()
            out = Path(tmp) / "site"
            quiet(main, ["site", "--runs", str(runs), "--out", str(out)])
            self.assertEqual(sorted(p.name for p in out.iterdir()), [".nojekyll", "index.html", "r1", "r2"])
            self.assertIn('href="r2/"', (out / "index.html").read_text(encoding="utf-8"))
            self.assertTrue((out / "r1" / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
