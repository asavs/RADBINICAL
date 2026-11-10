import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical import human
from radbinical.cli import main
from radbinical.config import DEFAULT_FLAGS
from radbinical.page import Page, cast_of, reader_entry

TEXT = "The laws of production are fixed. Distribution is a matter of human institution solely.\n\nA second paragraph."


def make_run(run_dir, rounds=2):
    """A small page on disk: two mock readers, one comment each per round, the second replying."""
    readers = [reader_entry(m) for m in ("mock:alef", "mock:bet")]
    data = {"passage": {"id": "t", "title": "T", "source": "", "text": TEXT}, "readers": readers,
            "cast": cast_of(readers), "group": Path(run_dir).name, "flags": dict(DEFAULT_FLAGS),
            "comments": [], "log": [], "counter": 0, "layers_done": 0, "started": "2026-01-01T00:00:00"}
    Path(run_dir).mkdir(parents=True, exist_ok=True)
    page = Page(data, run_dir)
    for layer in range(1, rounds + 1):
        page.add("alef", layer, {"target": "passage", "quote": "laws of production", "text": f"gloss {layer}"})
        page.add("bet", layer, {"target": "c1", "quote": "gloss", "text": f"reply {layer}"})
        data["log"] += [{"layer": layer, "reader": r, "model": "mock:" + r, "comments": 1, "usage": {}} for r in ("alef", "bet")]
        data["layers_done"] = layer
    page.save()
    return page


def sub(blind=False, comments=None, name="Ruth"):
    return {"name": name, "blind": blind, "saw_models": not blind,
            "comments": comments or [{"target": "passage", "quote": "human institution", "text": "A person's gloss."}]}


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        try:
            main([str(a) for a in argv])
            code = 0
        except SystemExit as e:
            code = 0 if e.code in (0, None) else 1
    return code, out.getvalue()


class Submissions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.run = self.root / "runs" / "r1"
        make_run(self.run)

    def tearDown(self):
        self.tmp.cleanup()

    def page(self):
        return json.loads((self.run / "page.json").read_text(encoding="utf-8"))

    def test_good_submission_is_added_after_the_last_round(self):
        errs, ids = human.add(self.run, sub(comments=[
            {"target": "passage", "quote": "human institution", "text": "A gloss."},
            {"target": "c1", "quote": "gloss 1", "text": "A reply.", "see_also": ["c2"]}]), "ruth.json")
        self.assertEqual(errs, [])
        self.assertEqual(len(ids), 2)
        d = self.page()
        new = [c for c in d["comments"] if c["id"] in ids]
        self.assertTrue(all(c["kind"] == "human" and c["author"] == "Ruth" and c["layer"] == 3 for c in new))
        self.assertEqual(new[0]["meta"], {"submission": "ruth.json", "blind": False, "saw_models": True})
        self.assertEqual(new[1]["see_also"], ["c2"])
        self.assertEqual(d["layers_done"], 3)
        self.assertIn({"name": "Ruth", "model": "human:ruth", "human": True}, d["readers"])
        self.assertTrue((self.run / "page.html").exists())

    def test_people_before_the_next_model_round_share_a_round(self):
        human.add(self.run, sub(), "ruth.json")
        human.add(self.run, sub(name="Asa"), "asa.json")
        d = self.page()
        self.assertEqual({c["layer"] for c in d["comments"] if c.get("kind") == "human"}, {3})
        self.assertEqual(d["layers_done"], 3)

    def test_adding_twice_adds_nothing(self):
        human.add(self.run, sub(), "ruth.json")
        before = self.page()
        errs, ids = human.add(self.run, sub(), "ruth.json")
        self.assertEqual((errs, ids), ([], []))
        self.assertEqual(self.page(), before)

    def test_bad_quote(self):
        errs, ids = human.add(self.run, sub(comments=[{"target": "passage", "quote": "surplus value", "text": "x"}]), "ruth.json")
        self.assertTrue(errs and "not found" in errs[0])
        self.assertEqual(len(self.page()["comments"]), 4)

    def test_bad_quote_in_a_reply_and_unknown_ids(self):
        for c in ({"target": "c1", "quote": "not in that comment", "text": "x"},
                  {"target": "c99", "text": "x"},
                  {"target": "passage", "quote": "laws of production", "text": "x", "see_also": ["c42"]}):
            self.assertTrue(human.problems(self.run, sub(comments=[c]), "ruth.json"), c)

    def test_shape(self):
        for s in ({"name": "", "blind": False, "saw_models": True, "comments": [{"target": "passage", "quote": "laws", "text": "x"}]},
                  {"name": "R", "blind": "no", "saw_models": True, "comments": [{"target": "passage", "quote": "laws", "text": "x"}]},
                  {"name": "R", "blind": True, "saw_models": True, "comments": [{"target": "passage", "quote": "laws", "text": "x"}]},
                  {"name": "R", "blind": False, "saw_models": True, "comments": []}):
            self.assertTrue(human.problems(self.run, s, "r.json"), s)

    def test_blind_is_round_one_and_passage_only(self):
        errs, _ = human.add(self.run, sub(blind=True, comments=[{"target": "c1", "text": "a reply"}]), "ruth.json")
        self.assertTrue(errs and "blind" in errs[0])
        errs, ids = human.add(self.run, sub(blind=True), "ruth.json")
        self.assertEqual(errs, [])
        d = self.page()
        c = next(c for c in d["comments"] if c["id"] == ids[0])
        self.assertEqual((c["layer"], c["meta"]["blind"]), (1, True))
        self.assertEqual(d["layers_done"], 2)

    def test_blind_only_once(self):
        human.add(self.run, sub(), "ruth.json")
        errs, _ = human.add(self.run, sub(blind=True), "ruth-blind.json")
        self.assertTrue(errs)

    def test_a_model_name_cannot_be_taken(self):
        self.assertTrue(human.problems(self.run, sub(name="alef"), "alef.json"))

    def test_blind_on_an_unrun_page_leaves_round_one_to_the_models(self):
        fresh = self.root / "runs" / "r0"
        make_run(fresh, rounds=0)
        human.add(fresh, sub(blind=True), "ruth.json")
        d = json.loads((fresh / "page.json").read_text(encoding="utf-8"))
        self.assertEqual((d["layers_done"], d["comments"][0]["layer"]), (0, 1))

    def test_cast_and_table_survive_a_person(self):
        from radbinical.table import rows, runs
        human.add(self.run, sub(), "ruth.json")
        self.assertEqual(self.page()["cast"], cast_of([reader_entry(m) for m in ("mock:alef", "mock:bet")]))
        r = [x for x in rows(self.root / "runs") if x["kind"] == "human"]
        self.assertEqual((r[0]["model"], r[0]["reader"]), ("human:ruth", "Ruth"))
        self.assertEqual(runs(self.root / "runs")[0]["comments"], 5)


class Commands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runs = self.root / "runs"
        make_run(self.runs / "r1")
        (self.root / "humans" / "r1").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, s):
        f = self.root / "humans" / "r1" / name
        f.write_text(json.dumps(s), encoding="utf-8")
        return f

    def test_check_exit_codes(self):
        self.write("ruth.json", sub())
        self.assertEqual(run_cli("human", "check", self.root / "humans", "--runs", self.runs)[0], 0)
        self.write("bad.json", sub(comments=[{"target": "passage", "quote": "nowhere in it", "text": "x"}]))
        code, out = run_cli("human", "check", self.root / "humans", "--runs", self.runs)
        self.assertEqual(code, 1)
        self.assertIn("bad.json", out)
        (self.root / "humans" / "r1" / "broken.json").write_text("{", encoding="utf-8")
        self.assertEqual(run_cli("human", "check", self.root / "humans" / "r1" / "broken.json", "--runs", self.runs)[0], 1)

    def test_check_writes_nothing(self):
        before = (self.runs / "r1" / "page.json").read_text(encoding="utf-8")
        run_cli("human", "check", self.write("ruth.json", sub()), "--runs", self.runs)
        self.assertEqual((self.runs / "r1" / "page.json").read_text(encoding="utf-8"), before)

    def test_add_then_add_again(self):
        f = self.write("ruth.json", sub())
        self.assertEqual(run_cli("human", "add", self.runs / "r1", "--file", f), (0, "added c5\n"))
        self.assertIn("nothing added", run_cli("human", "add", self.runs / "r1", "--file", f)[1])

    def test_template(self):
        code, out = run_cli("human", "template", self.runs / "r1", "--blind")
        self.assertEqual(code, 0)
        self.assertIn("laws of production", out)
        self.assertNotIn("gloss 1", out)
        self.assertEqual(json.loads(out.split("===\n", 1)[1])["blind"], True)
        self.assertIn("gloss 1", run_cli("human", "template", self.runs / "r1")[1])


if __name__ == "__main__":
    unittest.main()
