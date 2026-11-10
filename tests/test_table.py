import json
import tempfile
import unittest
from pathlib import Path

from radbinical.config import DEFAULT_FLAGS
from radbinical.page import Page, cast_of, reader_entry
from radbinical.table import rows, runs, write_jsonl

TEXT = "The laws of production are fixed. Distribution is a matter of human institution solely."


def make_run(base, name, group, lineage=None):
    readers = [reader_entry(m) for m in ("mock:alef", "mock:bet")]
    data = {"passage": {"id": "mill-property", "title": "T", "source": "", "text": TEXT},
            "readers": readers, "cast": cast_of(readers), "group": group,
            "flags": dict(DEFAULT_FLAGS), "comments": [], "log": [], "counter": 0, "layers_done": 2, "started": "2026-01-01T00:00:00"}
    if lineage:
        data["lineage"] = lineage
    d = Path(base) / name
    d.mkdir()
    page = Page(data, d)
    page.add("alef", 1, {"target": "passage", "quote": "laws of production", "text": "gloss"})
    page.add("bet", 1, {"target": "passage", "quote": "human institution", "text": "other"}, kind="plant", meta={"truth": "x"})
    page.add("bet", 2, {"target": "c1", "quote": "gloss", "text": "reply", "see_also": ["c2"]})
    page.add("alef", 2, {"target": "c3", "text": "reply to reply"})
    data["log"] = [{"usage": {"cost": 0.25}}, {"usage": {"prompt_tokens": 9}}, {"usage": {}}]
    page.save()
    return page


class Table(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        make_run(self.base, "b-run", "g1", lineage="L1")
        p = make_run(self.base, "a-run", "g1")
        p.save_side("redactions", {"items": [], "usage": [{"cost": 0.5}, {"cost": 0.125}]})
        p.save_side("notes", ["a list, no usage"])
        (Path(self.base) / "not-a-run").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_comment_rows(self):
        r = rows(self.base)
        self.assertEqual([x["run"] for x in r], ["a-run"] * 4 + ["b-run"] * 4)
        c1, c2, c3, c4 = r[:4]
        self.assertEqual(list(c1), ["run", "passage", "cast", "group", "lineage", "model", "reader", "round", "id",
                                    "parent", "root", "depth", "start", "end", "quote", "text", "see_also", "kind"])
        self.assertEqual((c1["parent"], c1["root"], c1["depth"], c1["kind"], c1["model"]), (None, "c1", 0, None, "mock:alef"))
        self.assertEqual(TEXT[c1["start"]:c1["end"]], "laws of production")
        self.assertEqual(c2["kind"], "plant")
        self.assertNotIn("meta", c2)
        self.assertEqual((c3["parent"], c3["root"], c3["depth"], c3["quote"], c3["see_also"]), ("c1", "c1", 1, "gloss", ["c2"]))
        self.assertEqual((c4["parent"], c4["root"], c4["depth"], c4["quote"], c4["round"]), ("c3", "c1", 2, None, 2))
        self.assertEqual((c3["start"], c3["end"]), (c1["start"], c1["end"]))
        self.assertEqual((c4["start"], c4["end"]), (c1["start"], c1["end"]))
        self.assertEqual((r[0]["lineage"], r[4]["lineage"]), (None, "L1"))

    def test_run_rows(self):
        a, b = runs(self.base)
        self.assertEqual((a["run"], a["passage"], a["group"], a["rounds"], a["comments"]), ("a-run", "mill-property", "g1", 2, 4))
        self.assertEqual(a["cast"], cast_of(["mock:bet", "mock:alef"]))
        self.assertEqual(a["readers"], [{"name": "alef", "model": "mock:alef"}, {"name": "bet", "model": "mock:bet"}])
        self.assertEqual(a["cost"], 0.875)   # log plus redactions.json
        self.assertEqual(b["cost"], 0.25)
        self.assertEqual(b["lineage"], "L1")

    def test_jsonl_is_utf8_and_stable(self):
        out = Path(self.base) / "data" / "x.jsonl"
        write_jsonl(out, [{"t": "é"}, {"t": 2}])
        first = out.read_bytes()
        self.assertEqual(first.decode("utf-8").splitlines(), ['{"t": "é"}', '{"t": 2}'])
        write_jsonl(out, [{"t": "é"}, {"t": 2}])
        self.assertEqual(out.read_bytes(), first)


class Identity(unittest.TestCase):
    def test_cast_is_order_free_and_short(self):
        self.assertEqual(cast_of(["mock:a", "x/y"]), cast_of([{"model": "x/y"}, {"model": "mock:a"}]))
        self.assertNotEqual(cast_of(["mock:a"]), cast_of(["mock:b"]))
        self.assertEqual(len(cast_of(["mock:a"])), 8)

    def test_committed_runs_carry_identity(self):
        from radbinical.table import run_dirs
        for d in run_dirs():
            p = json.loads((d / "page.json").read_text(encoding="utf-8"))
            self.assertTrue(p["passage"]["id"] and p["group"], d)
            self.assertEqual(p["cast"], cast_of(p["readers"]), d)


if __name__ == "__main__":
    unittest.main()
