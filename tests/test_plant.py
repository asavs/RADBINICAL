import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical.cli import main
from radbinical.commands.plant import add_plant
from radbinical.config import DEFAULT_FLAGS
from radbinical.page import Page, render_for_reader

TEXT = "The laws of Production partake of the character of physical truths. Distribution is a matter of human institution solely."


def make_page(d, layers_done=2):
    """A page in folder d with two readers and two comments in round 1."""
    data = {"passage": {"id": "t", "title": "T", "source": "", "text": TEXT},
            "readers": [{"model": "mock:alef", "name": "alef"}, {"model": "mock:bet", "name": "bet"}],
            "cast": "x", "group": "g", "flags": dict(DEFAULT_FLAGS), "comments": [], "log": [],
            "counter": 0, "layers_done": layers_done}
    page = Page(data, d)
    page.add("alef", 1, {"target": "passage", "quote": "physical truths", "text": "Physical, as in natural law."})
    page.add("bet", 1, {"target": "c1", "text": "Natural law is too strong."})
    page.save()
    return page


def run(argv):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        main(argv)
    return out.getvalue()


class Plant(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "r"
        self.dir.mkdir()
        make_page(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cli_plant_stores_kind_and_meta_and_renders(self):
        out = run(["plant", str(self.dir), "--as", "bet", "--sort", "slip", "--target", "passage",
                   "--quote", "human institution", "--text", "Mill wrote this in 1859.", "--truth", "It was 1848."])
        self.assertIn("c3", out)
        page = Page.load(self.dir)
        c = page.d["comments"][-1]
        self.assertEqual((c["id"], c["author"], c["layer"], c["kind"]), ("c3", "bet", 2, "plant"))
        self.assertEqual(c["meta"], {"sort": "slip", "truth": "It was 1848."})
        self.assertEqual(c["quote"], "human institution")
        html = (self.dir / "page.html").read_text(encoding="utf-8")
        self.assertIn("Mill wrote this in 1859.", html)

    def test_hidden_from_readers(self):
        page = Page.load(self.dir)
        ok, _ = add_plant(page, {"as": "alef", "sort": "sound", "target": "c2", "text": "Natural law is right here.",
                                 "truth": "SECRET-NOTE holds because ..."})
        self.assertTrue(ok)
        view = render_for_reader(page.d, page.d["comments"], lambda a: a, "bet")
        self.assertIn("Natural law is right here.", view)
        self.assertNotIn("SECRET-NOTE", view)
        self.assertNotIn("plant", view)
        self.assertNotIn("sound", view)

    def test_round_default_and_explicit(self):
        page = Page.load(self.dir)
        add_plant(page, {"as": "alef", "sort": "slip", "target": "c1", "text": "x", "truth": "y", "round": 1})
        self.assertEqual(page.d["comments"][-1]["layer"], 1)
        ok, msg = add_plant(page, {"as": "alef", "sort": "slip", "target": "c1", "text": "x", "truth": "y", "round": 3})
        self.assertFalse(ok)
        self.assertIn("between 1 and 2", msg)

    def test_errors_are_reported(self):
        page = Page.load(self.dir)
        cases = [
            ({"as": "nobody", "sort": "slip", "target": "c1", "text": "x", "truth": "y"}, "no model reader named"),
            ({"as": "alef", "sort": "odd", "target": "c1", "text": "x", "truth": "y"}, "sort must be"),
            ({"as": "alef", "sort": "slip", "target": "c1", "text": "x", "truth": " "}, "truth is empty"),
            ({"as": "alef", "sort": "slip", "target": "passage", "quote": "not in the text at all", "text": "x", "truth": "y"}, "not found in the passage"),
            ({"as": "alef", "sort": "slip", "target": "passage", "text": "x", "truth": "y"}, "needs `quote`"),
            ({"as": "alef", "sort": "slip", "target": "c99", "text": "x", "truth": "y"}, 'no comment with id "c99"'),
            ({"as": "alef", "sort": "slip", "target": "c1", "text": "", "truth": "y"}, "text is empty"),
        ]
        for p, want in cases:
            ok, msg = add_plant(page, p)
            self.assertFalse(ok, p)
            self.assertIn(want, msg)
        self.assertEqual(len(page.d["comments"]), 2)

    def test_file_is_all_or_nothing(self):
        f = Path(self.tmp.name) / "plants.json"
        good = {"as": "alef", "sort": "slip", "target": "c2", "text": "a", "truth": "b"}
        f.write_text(json.dumps([good, {**good, "target": "c42"}]), encoding="utf-8")
        with self.assertRaises(SystemExit) as e:
            run(["plant", str(self.dir), "--file", str(f)])
        self.assertIn("plant 2", str(e.exception))
        self.assertEqual(len(Page.load(self.dir).d["comments"]), 2)
        f.write_text(json.dumps([good, {**good, "sort": "sound", "target": "c3", "see_also": ["c1"]}]), encoding="utf-8")
        run(["plant", str(self.dir), "--file", str(f)])
        cs = Page.load(self.dir).d["comments"]
        self.assertEqual([(c["id"], c["target"], c.get("kind")) for c in cs[2:]], [("c3", "c2", "plant"), ("c4", "c3", "plant")])
        self.assertEqual(cs[3]["see_also"], ["c1"])

    def test_missing_options(self):
        with self.assertRaises(SystemExit) as e:
            run(["plant", str(self.dir), "--as", "alef", "--sort", "slip"])
        self.assertIn("--target", str(e.exception))


if __name__ == "__main__":
    unittest.main()
