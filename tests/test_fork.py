import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical.cli import main
from radbinical.commands.fork import fork
from radbinical.commands.run import run_config
from radbinical.config import ROOT
from radbinical.page import Page, cast_of
from radbinical.rounds import run_layers
from radbinical.table import rows, runs


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


def load(d):
    return json.loads((Path(d) / "page.json").read_text(encoding="utf-8"))


class Fork(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = json.loads((ROOT / "config.mock.json").read_text(encoding="utf-8"))
        cfg["passage"]["file"] = str(ROOT / cfg["passage"]["file"])
        cfg["flags"] = {"max_layers": 2, "seed": 7, "stop_when_all_pass": False}
        config = Path(self.tmp.name) / "c.json"
        config.write_text(json.dumps(cfg), encoding="utf-8")
        self.runs = Path(self.tmp.name) / "runs"
        [(self.src, _)] = quiet(run_config, config, self.runs / "mill")
        page = Page.load(self.src)
        page.d["log"][0]["usage"] = {"cost": 0.5}
        page.save()
        page.save_side("amendments", {"versions": [{"n": 1}], "usage": [{"cost": 0.25}]})
        page.save_side("redactions", {"items": [], "usage": [{"cost": 1.0}]})
        self.before = load(self.src)

    def tearDown(self):
        self.tmp.cleanup()

    def test_copies_carry_identity(self):
        done = quiet(fork, self.src, 3)
        self.assertEqual([p.dir.name for p, _ in done], ["mill-s1", "mill-s2", "mill-s3"])
        for i, (p, ok) in enumerate(done, 1):
            d = load(p.dir)
            self.assertTrue(ok)
            self.assertEqual((d["lineage"], d["group"]), ("mill", f"mill-s{i}"))
            self.assertEqual(d["forked_from"], {"run": "mill", "round": 2, "comments": self.before["counter"]})
            self.assertEqual(d["flags"]["seed"], 7 + i)
            self.assertEqual(d["comments"], self.before["comments"])
            self.assertTrue((p.dir / "page.html").exists())
        self.assertEqual(load(self.src), self.before)

    def test_side_files_and_cost(self):
        quiet(fork, self.src, 1)
        copy = self.runs / "mill-s1"
        self.assertEqual(json.loads((copy / "amendments.json").read_text(encoding="utf-8")),
                         {"versions": [{"n": 1}], "usage": []})
        self.assertFalse((copy / "redactions.json").exists())
        d = load(copy)
        self.assertTrue(all("usage" not in e and e["from"] == "mill" for e in d["log"]))
        cost = {r["run"]: r["cost"] for r in runs(self.runs)}
        self.assertEqual(cost, {"mill": 1.75, "mill-s1": 0})

    def test_extended_copies_are_independent(self):
        done = quiet(fork, self.src, 2, rounds=1)
        a, b = (load(p.dir) for p, _ in done)
        self.assertEqual((a["layers_done"], b["layers_done"]), (3, 3))
        n = len(self.before["comments"])
        self.assertTrue(len(a["comments"]) > n and len(b["comments"]) > n)
        quiet(run_layers, Page.load(done[0][0].dir), 1)
        self.assertEqual(load(done[1][0].dir), b)
        self.assertEqual(load(self.src), self.before)
        self.assertEqual(load(done[0][0].dir)["layers_done"], 4)

    def test_table_rows_carry_lineage(self):
        quiet(fork, self.src, 2)
        by_run = {}
        for r in rows(self.runs):
            by_run.setdefault(r["run"], set()).add((r["lineage"], r["group"]))
        self.assertEqual(by_run, {"mill": {(None, "mill")}, "mill-s1": {("mill", "mill-s1")}, "mill-s2": {("mill", "mill-s2")}})

    def test_table_marks_inherited_comments(self):
        [(p, _)] = quiet(fork, self.src, 1, rounds=1)
        rs = [r for r in rows(self.runs) if r["run"] == "mill-s1"]
        n = len(self.before["comments"])
        self.assertTrue(all(r["inherited"] for r in rs[:n]))
        self.assertTrue(rs[n:] and not any(r["inherited"] for r in rs[n:]))
        self.assertFalse(any(r["inherited"] for r in rows(self.runs) if r["run"] == "mill"))

    def test_models_and_unsigned_through_cli(self):
        with self.assertRaises(SystemExit) as e:
            quiet(main, ["fork", str(self.src), "--into", "2", "-n", "1", "--models", "mock:he", "--unsigned"])
        self.assertEqual(e.exception.code, 0)
        for i in (1, 2):
            d = load(self.runs / f"mill-s{i}")
            self.assertEqual(d["readers"][-1]["name"], "he")
            self.assertEqual(d["cast"], cast_of(d["readers"]))
            self.assertFalse(d["flags"]["signed"])
            self.assertTrue(any(e["reader"] == "he" for e in d["log"] if "from" not in e))
        self.assertTrue(load(self.src)["flags"]["signed"])

    def test_start_and_only_new(self):
        quiet(fork, self.src, 1, rounds=1, models="mock:he")
        [(p, ok)] = quiet(fork, self.src, 1, rounds=1, models="mock:he", unsigned=True, start=2, only_new=True)
        self.assertTrue(ok)
        self.assertEqual(p.dir.name, "mill-s2")
        d = load(p.dir)
        self.assertEqual(d["flags"]["seed"], 7 + 2)
        fresh = [e for e in d["log"] if "from" not in e]
        self.assertEqual({e["reader"] for e in fresh}, {"he"})
        self.assertEqual({e["layer"] for e in fresh}, {3})
        self.assertTrue(all(c["author"] == "he" for c in d["comments"][len(self.before["comments"]):]))
        self.assertNotIn("max_tokens", d["readers"][-1])
        s1 = load(self.runs / "mill-s1")
        self.assertTrue(len({e["reader"] for e in s1["log"] if "from" not in e}) > 1)
        with self.assertRaises(SystemExit):
            quiet(fork, self.src, 1, rounds=1, models="mock:alef", start=3, only_new=True)
        self.assertFalse((self.runs / "mill-s3").exists())

    def test_extend_only_new(self):
        with self.assertRaises(SystemExit) as e:
            quiet(main, ["extend", str(self.src), "-n", "1", "--models", "mock:he", "--only-new", "--max-tokens", "32000"])
        self.assertEqual(e.exception.code, 0)
        d = load(self.src)
        self.assertEqual(d["readers"][-1], {"model": "mock:he", "name": "he", "max_tokens": 32000})
        self.assertEqual({e["reader"] for e in d["log"] if e["layer"] == 3}, {"he"})
        with self.assertRaises(SystemExit) as e:
            quiet(main, ["extend", str(self.src), "-n", "1", "--only-new"])
        self.assertNotEqual(e.exception.code, 0)

    def test_refuses_existing_copies(self):
        quiet(fork, self.src, 1)
        with self.assertRaises(SystemExit):
            quiet(fork, self.src, 2)
        self.assertFalse((self.runs / "mill-s2").exists())


if __name__ == "__main__":
    unittest.main()
