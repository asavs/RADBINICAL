import json
import re
import tempfile
import unittest
from pathlib import Path

from radbinical.config import ROOT
from radbinical.page import write_side
from radbinical.site import WORKFLOW, index_items, render

from test_human import make_run


def embedded(run_dir):
    html = (Path(run_dir) / "page.html").read_text(encoding="utf-8")
    blob = re.search(r"const D = (.*?);\nconst \$", html, re.S).group(1)
    return json.loads(blob.replace("<\\/", "</")), html


def page(name, group=None, lineage=None):
    d = {"passage": {"title": "T " + name}, "readers": [{"name": "a", "model": "mock:a"}], "comments": [], "layers_done": 1,
         "group": group or name, "started": "2026-01-01"}
    if lineage:
        d["lineage"] = lineage
    return name, d


class Render(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name) / "r1"
        make_run(self.run)

    def tearDown(self):
        self.tmp.cleanup()

    def test_without_side_files(self):
        render(self.run)
        d, html = embedded(self.run)
        self.assertEqual(d["side"], {})
        self.assertEqual(d["site"], {"run": "r1", "workflow": WORKFLOW})
        self.assertIn("Another round", html)
        self.assertIn('id="print"', html)

    def test_side_files_are_embedded(self):
        write_side(self.run, "plants", {"judge": "j", "plants": []})
        write_side(self.run, "forecasts", {"forecasts": [{"round": 2, "reader": "alef", "hits": ["c1"]}]})
        write_side(self.run, "unrelated", {"x": 1})
        render(self.run)
        d, _ = embedded(self.run)
        self.assertEqual(set(d["side"]), {"plants", "forecasts"})
        self.assertEqual(d["side"]["forecasts"]["forecasts"][0]["hits"], ["c1"])
        self.assertNotIn("side", json.loads((self.run / "page.json").read_text(encoding="utf-8")))

    def test_side_text_cannot_close_the_script(self):
        write_side(self.run, "redactions", {"redactions": [{"name": "x", "items": [{"status": "settled", "summary": "</script><b>"}]}]})
        render(self.run)
        _, html = embedded(self.run)
        self.assertEqual(html.count("</script>"), 1)


class Index(unittest.TestCase):
    def test_repeats_share_an_entry(self):
        out = index_items([page("m-a", "m"), page("m-b", "m"), page("solo")], {})
        self.assertEqual(out.count("<li>"), 2)
        self.assertIn("run 2 times", out)
        self.assertIn('href="m-b/"', out)

    def test_forks_sit_under_their_source(self):
        out = index_items([page("src"), page("src-f1", lineage="src"), page("src-f2", lineage="src"), page("f1-f", lineage="src-f1")], {})
        self.assertEqual(out.count('<ul class="forks">'), 2)
        top = out.split('<ul class="forks">')[0]
        self.assertNotIn("src-f1", top)
        self.assertLess(out.index('href="src-f1/"'), out.index('href="f1-f/"'))

    def test_fork_of_a_missing_run_stands_alone(self):
        out = index_items([page("orphan", lineage="gone")], {})
        self.assertIn('href="orphan/"', out)
        self.assertNotIn("forks", out)


class Workflow(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github" / "workflows" / "run.yml").read_text(encoding="utf-8")

    def test_inputs(self):
        inputs = self.text.split("inputs:", 1)[1].split("permissions:", 1)[0]
        for name in ("mode", "config", "name", "rounds", "models", "repeat"):
            self.assertRegex(inputs, rf"\n      {name}:")
        for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            self.assertIn(f"{key}: ${{{{ secrets.{key} }}}}", self.text)

    def test_no_input_inside_a_run_line(self):
        lines, inside, indent = self.text.splitlines(), False, 0
        for line in lines:
            stripped = line.lstrip(" -")
            ind = len(line) - len(line.lstrip(" "))
            if inside and line.strip() and ind <= indent:
                inside = False
            if stripped.startswith("run:") and ind >= 6:  # a step's shell, not the job named "run"
                inside, indent = True, ind
            if inside:
                self.assertNotIn("${{", line, line)

    def test_commits_runs_data_and_docs(self):
        self.assertIn("git add runs data docs", self.text)
        self.assertIn("python3 -m radbinical table", self.text)

    def test_tests_check_submissions(self):
        self.assertIn("radbinical human check humans", (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
