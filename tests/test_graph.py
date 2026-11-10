import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical.cli import main
from radbinical.commands.graph import nodes, run_summaries
from radbinical.config import DEFAULT_FLAGS
from radbinical.page import Page, cast_of, reader_entry
from radbinical.table import rows

TEXT = "The laws of production are fixed. Distribution is a matter of human institution solely."


def make_page(base, name):
    readers = [reader_entry(m) for m in ("mock:alef", "mock:bet", "mock:gimel")]
    data = {"passage": {"id": "mill", "title": "T", "source": "", "text": TEXT}, "readers": readers,
            "cast": cast_of(readers), "group": name, "flags": dict(DEFAULT_FLAGS), "comments": [], "log": [],
            "counter": 0, "layers_done": 3}
    d = Path(base) / name
    d.mkdir()
    return Page(data, d)


class Graph(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = make_page(self.tmp.name, "run")
        for who, rnd, args in [
            ("alef", 1, {"target": "passage", "quote": "laws of production", "text": "one"}),        # c1
            ("bet", 1, {"target": "passage", "quote": "human institution", "text": "two"}),          # c2
            ("bet", 2, {"target": "c1", "text": "three", "see_also": ["c2"]}),                       # c3
            ("alef", 2, {"target": "c3", "text": "four"}),                                           # c4
            ("gimel", 3, {"target": "passage", "quote": "Distribution", "text": "five", "see_also": ["c1"]}),  # c5
        ]:
            ok, msg = p.add(who, rnd, args)
            self.assertTrue(ok, msg)
        p.save()
        self.rows = rows(self.tmp.name)
        self.nodes = {n["id"]: n for n in nodes(self.rows)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_degrees_and_descendants(self):
        c1, c2, c3, c4, c5 = (self.nodes[f"c{i}"] for i in range(1, 6))
        self.assertEqual((c1["replies_in"], c1["see_also_in"], c1["descendants"], c1["subtree_readers"]), (1, 1, 2, 2))
        self.assertEqual(c1["builds_on"], 2)            # c3 (bet) and c5 (gimel); c4 is alef's own
        self.assertEqual((c2["replies_in"], c2["see_also_in"], c2["descendants"], c2["builds_on"]), (0, 1, 0, 0))   # cited only by bet's own c3
        self.assertEqual((c3["replies_in"], c3["descendants"], c3["builds_on"], c3["depth"]), (1, 1, 1, 1))
        self.assertEqual((c4["depth"], c4["builds_on"]), (2, 0))
        self.assertEqual((c5["see_also"], c5["builds_on"]), (["c1"], 0))

    def test_run_summary(self):
        [s] = run_summaries(self.rows, list(self.nodes.values()))
        self.assertEqual((s["comments"], s["share_no_replies"], s["max_depth"]), (5, 0.6, 2))
        self.assertEqual(s["replies"], {"alef": {"bet": 1}, "bet": {"alef": 1}})
        self.assertEqual((s["reader_pairs_linked"], s["reader_pairs_mutual"], s["reciprocity"]), (1, 1, 1.0))

    def test_command(self):
        out = Path(self.tmp.name) / "data"
        with contextlib.redirect_stdout(io.StringIO()) as s:
            main(["graph", "--runs", self.tmp.name, "--out", str(out)])
        lines = (out / "graph.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(x)["id"] for x in lines], ["c1", "c2", "c3", "c4", "c5"])
        self.assertTrue((out / "graph_runs.jsonl").exists())
        self.assertIn("c1", s.getvalue())


if __name__ == "__main__":
    unittest.main()
