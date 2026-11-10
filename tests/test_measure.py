import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical.cli import main
from radbinical.commands.measure import joiner_rows, rounds_rows
from radbinical.config import DEFAULT_FLAGS
from radbinical.page import Page, cast_of, reader_entry
from radbinical.readings import readings
from radbinical.table import rows, runs

TEXT = ("The laws of production are fixed. Distribution is a matter of human institution solely. "
        "Things once there may be placed anywhere.")
FIXED = "production laws fixed nature physical truths"


class Rounds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        readers = [reader_entry(m) for m in ("mock:alef", "mock:bet", "mock:gimel")]
        data = {"passage": {"id": "mill", "title": "T", "source": "", "text": TEXT}, "readers": readers,
                "cast": cast_of(readers), "group": "run", "flags": dict(DEFAULT_FLAGS), "comments": [], "log": [],
                "counter": 0, "layers_done": 3}
        d = Path(self.tmp.name) / "run"
        d.mkdir()
        p = Page(data, d)
        for who, rnd, args, *kind in [
            ("alef", 1, {"target": "passage", "quote": "laws of production are fixed", "text": FIXED}),       # c1
            ("bet", 1, {"target": "passage", "quote": "human institution solely", "text": "society chooses arrangement"}),  # c2
            ("bet", 2, {"target": "c1", "text": "technology moves"}),                                         # c3
            ("alef", 2, {"target": "passage", "quote": "Things once there", "text": "stock already produced"}),  # c4
            ("gimel", 3, {"target": "c1", "text": "old layer reply"}),                                        # c5, age 2
            ("gimel", 3, {"target": "passage", "quote": "matter of human", "text": "legal convention matters",
                          "see_also": ["c2"]}),                                                               # c6, age 2
            ("gimel", 3, {"target": "passage", "quote": "laws of production are fixed", "text": FIXED + " indeed"}),  # c7
            ("bet", 3, {"target": "c3", "text": "follow up"}),                                                # c8, age 1
            ("bet", 2, {"target": "passage", "quote": "Things once there", "text": "a plant " * 40}, "plant"),  # c9
            ("gimel", 3, {"target": "c9", "text": "reply to plant"}),                                         # c10, age 1
        ]:
            ok, msg = p.add(who, rnd, args, kind=kind[0] if kind else None)
            self.assertTrue(ok, msg)
        # alef and bet take a turn in every round, gimel only in round 3
        data["log"] = [{"layer": k, "reader": r, "model": f"mock:{r}", "comments": 0, "usage": {}}
                       for k, r in [(1, "alef"), (1, "bet"), (2, "alef"), (2, "bet"), (3, "alef"), (3, "bet"), (3, "gimel")]]
        p.save()
        self.rows = rows(self.tmp.name)
        self.runs = runs(self.tmp.name)
        _, self.members = readings(self.rows, "mock:bow", cache_dir=Path(self.tmp.name) / "emb")

    def tearDown(self):
        self.tmp.cleanup()

    def test_rounds(self):
        r1, r2, r3 = rounds_rows(self.rows, self.members)
        self.assertEqual((r1["comments"], r1["share_replies"], r1["share_older"], r1["new_readings"], r1["alive"], r1["cumulative"]),
                         (2, 0.0, None, 2, 2, 2))
        self.assertEqual((r2["comments"], r2["share_replies"], r2["share_older"], r2["new_readings"], r2["alive"], r2["cumulative"]),
                         (2, 0.5, None, 1, 2, 3))
        # the plant c9 is not counted in round 2; c10, a reply to it, is counted in round 3
        self.assertEqual((r3["comments"], r3["share_replies"], r3["share_older"], r3["new_readings"], r3["alive"], r3["cumulative"]),
                         (5, 0.6, 0.4, 1, 2, 4))
        self.assertEqual((r1["spans"], r2["spans"], r3["spans"]), (2, 2, 3))
        self.assertEqual(r2["mean_length"], (len("technology moves") + len("stock already produced")) / 2)

    def test_late_joiner(self):
        self.assertEqual([(r["name"], r["joined"]) for r in self.runs[0]["readers"]], [("alef", 1), ("bet", 1), ("gimel", 3)])
        [j] = joiner_rows(self.rows, self.runs)
        self.assertEqual((j["reader"], j["model"], j["joined"], j["comments"]), ("gimel", "mock:gimel", 3, 4))
        self.assertEqual((j["share_engaging"], j["share_fresh"]), (0.75, 0.25))
        self.assertEqual((j["mean_age"], j["max_age"], j["share_older"]), (1.67, 2, 0.6667))

    def test_joining_is_entering_the_page_not_first_commenting(self):
        # dalet took a turn in round 1 and commented only in round 3: not a late joiner.
        # he entered in round 3 and wrote nothing: a late joiner with no comments.
        rs = [{"run": "r", "id": "c1", "reader": "dalet", "round": 3, "parent": None, "see_also": [], "kind": None}]
        run_rows = [{"run": "r", "readers": [{"name": "dalet", "model": "mock:dalet", "joined": 1},
                                             {"name": "he", "model": "mock:he", "joined": 3},
                                             {"name": "vav", "model": "mock:vav", "joined": None}]}]
        [j] = joiner_rows(rs, run_rows)
        self.assertEqual((j["reader"], j["joined"], j["comments"], j["share_engaging"], j["mean_age"]), ("he", 3, 0, None, None))

    def test_command(self):
        out = Path(self.tmp.name) / "data"
        with contextlib.redirect_stdout(io.StringIO()) as s:
            main(["measure", "--runs", self.tmp.name, "--out", str(out), "--embed", "mock:bow"])
        lines = (out / "rounds.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(x)["round"] for x in lines], [1, 2, 3])
        self.assertEqual(json.loads((out / "joiners.jsonl").read_text(encoding="utf-8"))["reader"], "gimel")
        self.assertIn("late joiner gimel", s.getvalue())


if __name__ == "__main__":
    unittest.main()
