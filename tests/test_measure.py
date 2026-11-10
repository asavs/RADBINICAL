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
from radbinical.table import rows

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
        for who, rnd, args in [
            ("alef", 1, {"target": "passage", "quote": "laws of production are fixed", "text": FIXED}),       # c1
            ("bet", 1, {"target": "passage", "quote": "human institution solely", "text": "society chooses arrangement"}),  # c2
            ("bet", 2, {"target": "c1", "text": "technology moves"}),                                         # c3
            ("alef", 2, {"target": "passage", "quote": "Things once there", "text": "stock already produced"}),  # c4
            ("gimel", 3, {"target": "c1", "text": "old layer reply"}),                                        # c5, age 2
            ("gimel", 3, {"target": "passage", "quote": "matter of human", "text": "legal convention matters",
                          "see_also": ["c2"]}),                                                               # c6, age 2
            ("gimel", 3, {"target": "passage", "quote": "laws of production are fixed", "text": FIXED + " indeed"}),  # c7
            ("bet", 3, {"target": "c3", "text": "follow up"}),                                                # c8, age 1
        ]:
            ok, msg = p.add(who, rnd, args)
            self.assertTrue(ok, msg)
        p.save()
        self.rows = rows(self.tmp.name)
        _, self.members = readings(self.rows, "mock:bow", cache_dir=Path(self.tmp.name) / "emb")

    def tearDown(self):
        self.tmp.cleanup()

    def test_rounds(self):
        r1, r2, r3 = rounds_rows(self.rows, self.members)
        self.assertEqual((r1["comments"], r1["share_replies"], r1["share_older"], r1["new_readings"], r1["alive"], r1["cumulative"]),
                         (2, 0.0, None, 2, 2, 2))
        self.assertEqual((r2["comments"], r2["share_replies"], r2["share_older"], r2["new_readings"], r2["alive"], r2["cumulative"]),
                         (2, 0.5, None, 1, 2, 3))
        self.assertEqual((r3["comments"], r3["share_replies"], r3["share_older"], r3["new_readings"], r3["alive"], r3["cumulative"]),
                         (4, 0.5, 0.5, 1, 2, 4))
        self.assertEqual((r1["spans"], r3["spans"]), (2, 2))
        self.assertEqual(r2["mean_length"], (len("technology moves") + len("stock already produced")) / 2)

    def test_late_joiner(self):
        [j] = joiner_rows(self.rows)
        self.assertEqual((j["reader"], j["joined"], j["comments"]), ("gimel", 3, 3))
        self.assertEqual((j["share_engaging"], j["share_fresh"]), (0.6667, 0.3333))
        self.assertEqual((j["mean_age"], j["max_age"], j["share_older"]), (2.0, 2, 1.0))

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
