import contextlib
import io
import json
import pkgutil
import tempfile
import unittest
from pathlib import Path

from radbinical import commands
from radbinical.cli import main, parser
from radbinical.commands.run import run_config
from radbinical.config import ROOT
from radbinical.page import cast_of


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


class Discovery(unittest.TestCase):
    def test_every_module_is_a_command(self):
        sub = next(a for a in parser()._actions if a.dest == "cmd")
        names = {m.name for m in pkgutil.iter_modules(commands.__path__)}
        self.assertEqual(set(sub.choices), names)
        self.assertTrue({"run", "extend", "render", "site", "table"} <= names)

    def test_parse_sets_the_handler(self):
        a = parser().parse_args(["extend", "runs/x", "-n", "2"])
        self.assertEqual((a.run, a.n), ("runs/x", 2))
        self.assertTrue(callable(a.f))


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = json.loads((ROOT / "config.mock.json").read_text(encoding="utf-8"))
        self.cfg["passage"]["file"] = str(ROOT / self.cfg["passage"]["file"])
        self.cfg["flags"] = {"max_layers": 2, "seed": 5}
        self.config = Path(self.tmp.name) / "c.json"
        self.config.write_text(json.dumps(self.cfg), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_single_run_identity(self):
        out = Path(self.tmp.name) / "mill-x"
        [(d, ok)] = quiet(run_config, self.config, out)
        self.assertTrue(ok)
        p = json.loads((d / "page.json").read_text(encoding="utf-8"))
        self.assertEqual(d, out)
        self.assertEqual((p["passage"]["id"], p["group"], p["flags"]["seed"]), ("mill-property", "mill-x", 5))
        self.assertEqual(p["cast"], cast_of(self.cfg["models"]))
        self.assertTrue((d / "page.html").exists())

    def test_repeat(self):
        out = Path(self.tmp.name) / "mill-r"
        done = quiet(run_config, self.config, out, repeat=3)
        self.assertEqual([d.name for d, _ in done], ["mill-r-a", "mill-r-b", "mill-r-c"])
        self.assertFalse(out.exists())
        pages = [json.loads((d / "page.json").read_text(encoding="utf-8")) for d, _ in done]
        self.assertEqual({p["group"] for p in pages}, {"mill-r"})
        self.assertEqual({p["cast"] for p in pages}, {cast_of(self.cfg["models"])})
        self.assertEqual([p["flags"]["seed"] for p in pages], [5, 6, 7])

    def test_unknown_flag_is_rejected(self):
        self.cfg["flags"]["no_such_flag"] = 1
        self.config.write_text(json.dumps(self.cfg), encoding="utf-8")
        with self.assertRaises(SystemExit) as e:
            run_config(self.config, Path(self.tmp.name) / "bad")
        self.assertIn("no_such_flag", str(e.exception))

    def test_table_command_writes_jsonl(self):
        runs_dir = Path(self.tmp.name) / "runs"
        quiet(run_config, self.config, runs_dir / "m", repeat=2)
        quiet(main, ["table", "--runs", str(runs_dir), "--out", str(Path(self.tmp.name) / "data")])
        lines = (Path(self.tmp.name) / "data" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(x)["run"] for x in lines], ["m-a", "m-b"])
        rows = [json.loads(x) for x in (Path(self.tmp.name) / "data" / "comments.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(rows and all(r["group"] == "m" for r in rows))


if __name__ == "__main__":
    unittest.main()
