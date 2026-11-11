import json
import re
import tempfile
import unittest
from pathlib import Path

from radbinical.config import ROOT
from radbinical.site import WORKFLOW, index_items, render

from test_human import make_run


def embedded(run_dir):
    html = (Path(run_dir) / "page.html").read_text(encoding="utf-8")
    blob = re.search(r"const D = (.*?);\nconst \$", html, re.S).group(1)
    return json.loads(blob.replace("<\\/", "</")), html


def page(name, group=None):
    return name, {"passage": {"title": "T " + name}, "readers": [{"name": "a", "model": "mock:a"}], "comments": [], "layers_done": 1,
                  "group": group or name, "started": "2026-01-01"}


class Render(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name) / "r1"
        make_run(self.run)

    def tearDown(self):
        self.tmp.cleanup()

    def test_page_carries_its_record_and_the_kernel(self):
        render(self.run)
        d, html = embedded(self.run)
        self.assertEqual(d["site"], {"run": "r1", "workflow": WORKFLOW})
        self.assertIn("Another round", html)
        self.assertIn('id="print"', html)
        self.assertIn("function pieces(", html)
        self.assertNotIn("__KERNEL__", html)

    def test_page_text_cannot_close_the_script(self):
        d = json.loads((self.run / "page.json").read_text(encoding="utf-8"))
        d["comments"][0]["text"] = "</script><b>"
        (self.run / "page.json").write_text(json.dumps(d), encoding="utf-8")
        render(self.run)
        _, html = embedded(self.run)
        self.assertEqual(html.count("</script>"), 1)


class Index(unittest.TestCase):
    def test_repeats_share_an_entry(self):
        out = index_items([page("m-a", "m"), page("m-b", "m"), page("solo")], {})
        self.assertEqual(out.count("<li>"), 2)
        self.assertIn("run 2 times", out)
        self.assertIn('href="m-b/"', out)

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
