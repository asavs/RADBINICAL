import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from radbinical import embed as E
from radbinical.cli import main
from radbinical.config import DEFAULT_FLAGS
from radbinical.page import Page, cast_of, reader_entry
from radbinical.readings import noise, overlap, readings, recurrence
from radbinical.table import rows, runs

TEXT = "The laws of production are fixed. Distribution is a matter of human institution solely."
PHYSICAL = "production laws are physical truths fixed by nature and technology, beyond any human choosing"


def make_page(base, name, group, models=("mock:alef", "mock:bet")):
    readers = [reader_entry(m) for m in models]
    data = {"passage": {"id": "mill", "title": "T", "source": "", "text": TEXT}, "readers": readers,
            "cast": cast_of(readers), "group": group, "flags": dict(DEFAULT_FLAGS), "comments": [], "log": [],
            "counter": 0, "layers_done": 2}
    d = Path(base) / name
    d.mkdir()
    return Page(data, d)


def gloss(page, who, rnd, quote, text, **k):
    ok, msg = page.add(who, rnd, {"target": "passage", "quote": quote, "text": text}, **k)
    assert ok, msg


class Cache(unittest.TestCase):
    def test_hit_and_miss(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(E, "_fetch", wraps=E._fetch) as f:
            a = E.embed(["one text", "two text", "one text"], "mock:bow", tmp)
            self.assertEqual(f.call_args_list[-1].args, ("mock:bow", ["one text", "two text"]))
            self.assertEqual(a[0], a[2])
            b = E.embed(["two text", "three"], "mock:bow", tmp)
            self.assertEqual(f.call_count, 2)
            self.assertEqual(f.call_args_list[-1].args, ("mock:bow", ["three"]))
            self.assertEqual(b[0], a[1])
            E.embed(["three", "one text"], "mock:bow", tmp)
            self.assertEqual(f.call_count, 2)
            lines = (Path(tmp) / "mock-bow.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(x)["sha1"] for x in lines], [E.sha1(t) for t in ("one text", "two text", "three")])

    def test_bag_of_words_is_deterministic_and_graded(self):
        a, b = E.bag_of_words(PHYSICAL), E.bag_of_words(PHYSICAL + " indeed")
        c = E.bag_of_words("a rhetorical sleight: politics dressed in economics vocabulary")
        self.assertEqual(a, E.bag_of_words(PHYSICAL))
        self.assertGreater(E.cosine(a, b), 0.9)
        self.assertLess(E.cosine(a, c), 0.2)
        self.assertAlmostEqual(E.cosine(a, a), 1.0, places=4)

    def test_slug(self):
        self.assertEqual(E.slug("google:gemini-embedding-2"), "google-gemini-embedding-2")
        self.assertEqual(E.slug("openai/text-embedding-3-small"), "openai-text-embedding-3-small")


class Clustering(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        a = make_page(base, "g-a", "g")
        gloss(a, "alef", 1, "laws of production are fixed", PHYSICAL)                       # c1
        gloss(a, "alef", 1, "human institution solely", PHYSICAL)                           # c2, other span
        a.add("bet", 2, {"target": "c1", "text": "but technology changes"})                  # c3
        a.add("alef", 2, {"target": "c3", "text": "agreed, partly"})                         # c4
        a.add("bet", 2, {"target": "passage", "quote": "Distribution", "text": "x y z", "see_also": ["c1"]})  # c5
        a.save()
        b = make_page(base, "g-b", "g")
        gloss(b, "bet", 1, "The laws of production", PHYSICAL + " indeed")                  # near-identical
        gloss(b, "alef", 2, "laws of production are fixed", "a rhetorical sleight: politics dressed in economics vocabulary")
        gloss(b, "alef", 2, "human institution", "planted slip", kind="plant")
        b.save()
        self.rows = rows(base)
        self.readings, self.members = readings(self.rows, "mock:bow", cache_dir=Path(base) / "emb")
        self.of = {(m["run"], m["id"]): m["reading"] for m in self.members}

    def tearDown(self):
        self.tmp.cleanup()

    def test_overlap(self):
        self.assertEqual(overlap((0, 10), (5, 30)), 0.5)
        self.assertEqual(overlap((0, 10), (2, 4)), 1.0)
        self.assertEqual(overlap((0, 10), (10, 20)), 0.0)

    def test_same_span_same_meaning_clusters_across_runs(self):
        self.assertEqual(self.of[("g-a", "c1")], self.of[("g-b", "c1")])

    def test_same_span_other_meaning_does_not(self):
        self.assertNotEqual(self.of[("g-a", "c1")], self.of[("g-b", "c2")])

    def test_similar_text_on_other_span_does_not(self):
        self.assertNotEqual(self.of[("g-a", "c1")], self.of[("g-a", "c2")])

    def test_plants_and_replies_are_not_glosses(self):
        self.assertNotIn(("g-b", "c3"), self.of)
        self.assertNotIn(("g-a", "c3"), self.of)
        self.assertEqual(len(self.members), 5)

    def test_reading_row(self):
        r = next(x for x in self.readings if x["id"] == self.of[("g-a", "c1")])
        self.assertEqual((r["size"], r["runs"], r["groups"], r["first_round"]), (2, ["g-a", "g-b"], ["g"], {"g-a": 1, "g-b": 1}))
        self.assertEqual(r["models"], ["mock:alef", "mock:bet"])
        self.assertEqual((r["direct_replies"], r["replies"], r["cited"]), (1, 2, 1))
        self.assertEqual((r["other_repliers"], r["author_replied"]), (["bet"], 1))
        self.assertEqual(TEXT[r["start"]:r["end"]], "The laws of production are fixed")
        self.assertIn(r["representative"]["run"], ("g-a", "g-b"))


class Noise(unittest.TestCase):
    def test_recurrence_arithmetic(self):
        m = recurrence({"a": {1, 2, 3}, "b": {1, 2}, "c": {1, 4}}, ["a", "b", "c"])
        self.assertEqual((m["readings"], m["in_all"], m["in_2plus"], m["in_1"]), (4, 1, 2, 2))
        self.assertEqual((m["share_all"], m["share_2plus"], m["share_1"]), (0.25, 0.5, 0.5))
        self.assertAlmostEqual(m["jaccard"], round((2 / 3 + 1 / 4 + 1 / 3) / 3, 4))

    def test_noise_rows(self):
        def m(reading, run, cast, rnd):
            return {"reading": reading, "passage": "p", "run": run, "cast": cast, "round": rnd}
        members = [m("r1", "a", "X", 1), m("r1", "b", "X", 1), m("r2", "a", "X", 2), m("r2", "b", "X", 1),
                   m("r3", "c", "Y", 1), m("r1", "c", "Y", 2)]
        run_rows = [{"run": "a", "passage": "p", "group": "G", "cast": "X"},
                    {"run": "b", "passage": "p", "group": "G", "cast": "X"},
                    {"run": "c", "passage": "p", "group": "c", "cast": "Y"}]
        g, c = noise(members, run_rows)
        self.assertEqual((g["scope"], g["key"], g["units"]), ("group", "G", ["a", "b"]))
        self.assertEqual((g["all_rounds"]["share_all"], g["all_rounds"]["jaccard"]), (1.0, 1.0))
        self.assertEqual((g["round1"]["readings"], g["round1"]["share_all"], g["round1"]["jaccard"]), (2, 0.5, 0.5))
        self.assertEqual((c["scope"], c["units"]), ("casts", ["X", "Y"]))
        self.assertEqual((c["all_rounds"]["readings"], c["all_rounds"]["in_all"]), (3, 1))
        self.assertEqual((c["round1"]["in_all"], c["round1"]["in_1"]), (0, 3))


class Command(unittest.TestCase):
    def test_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("g-a", "g-b"):
                p = make_page(Path(tmp), name, "g")
                gloss(p, "alef", 1, "laws of production", PHYSICAL)
                p.save()
            out = Path(tmp) / "data"
            with contextlib.redirect_stdout(io.StringIO()) as s:
                main(["readings", "--runs", tmp, "--out", str(out), "--embed", "mock:bow"])
            rd = [json.loads(x) for x in (out / "readings.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["size"] for r in rd], [2])
            nz = [json.loads(x) for x in (out / "noise.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(nz[0]["round1"]["share_all"], 1.0)
            self.assertTrue((out / "reading_members.jsonl").exists() and (out / "embeddings" / "mock-bow.jsonl").exists())
            self.assertIn("group g", s.getvalue())
            self.assertEqual(len(runs(tmp)), 2)


if __name__ == "__main__":
    unittest.main()
