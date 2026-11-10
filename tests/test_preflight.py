import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from radbinical import preflight
from radbinical.commands.run import run_config
from radbinical.config import DEFAULT_FLAGS, ROOT
from radbinical.providers import http


class Answers:
    via, truncated = "somewhere", False

    def step(self):
        return "ready", {}


def opener(down):
    """An open_session whose readers in `down` cannot be reached."""
    def open_session(reader, system, user, flags):
        if reader["name"] in down:
            raise RuntimeError("HTTP 402: no credit")
        return Answers()
    return open_session


class Preflight(unittest.TestCase):
    def setUp(self):
        self.real = preflight.open_session
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        preflight.open_session = self.real
        self.tmp.cleanup()

    def test_says_who_answered_and_who_did_not(self):
        preflight.open_session = opener({"b"})
        readers = [{"name": "a", "model": "x/a"}, {"name": "b", "model": "x/b"}, {"name": "m", "model": "mock:m"}]
        got = preflight.preflight(readers, dict(DEFAULT_FLAGS))
        self.assertEqual([(r["name"], via, bool(err)) for r, via, err in got],
                         [("a", "somewhere", False), ("b", None, True), ("m", "mock", False)])
        self.assertIn("402", got[1][2])

    def test_does_not_wait_out_a_refusal_and_puts_the_retries_back(self):
        seen = []
        preflight.open_session = lambda *a: seen.append(http.ATTEMPTS) or Answers()
        before = http.ATTEMPTS
        preflight.preflight([{"name": "a", "model": "x/a"}], dict(DEFAULT_FLAGS))
        self.assertEqual((seen, http.ATTEMPTS), ([1], before))

    def test_a_run_does_not_start_while_a_reader_is_unreachable(self):
        preflight.open_session = opener({"Far"})
        cfg = json.loads((ROOT / "config.mock.json").read_text(encoding="utf-8"))
        cfg["models"] = ["mock:alef", {"model": "x/far", "name": "Far"}]
        cfg["passage"]["file"] = str(ROOT / cfg["passage"]["file"])
        path, out = Path(self.tmp.name) / "c.json", Path(self.tmp.name) / "run"
        path.write_text(json.dumps(cfg), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
            run_config(path, out)
        self.assertIn("Far could not be reached", str(stop.exception))
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
