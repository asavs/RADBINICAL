"""Turning a run's record into a web page, and all runs into a website."""
import html
import json
import re
from pathlib import Path

from .config import ROOT, TEMPLATES


HEAD = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n'


def render(run_dir):
    run_dir = Path(run_dir)
    data = json.loads((run_dir / "page.json").read_text())
    tpl = (TEMPLATES / "viewer.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    title = "Marginalia on " + re.sub(r"[<>&]", "", data["passage"]["title"])
    html = tpl.replace("__TITLE__", title).replace("/*__PAGE_DATA__*/null", blob)
    (run_dir / "page.html").write_text(html, encoding="utf-8")


def build_site():
    """Build docs/ for static hosting: one page per run plus an index."""
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / ".nojekyll").write_text("")
    rows = []
    for run in sorted((ROOT / "runs").iterdir()):
        if not (run / "page.json").exists():
            continue
        render(run)
        d = json.loads((run / "page.json").read_text())
        (docs / run.name).mkdir(exist_ok=True)
        (docs / run.name / "index.html").write_text(HEAD + (run / "page.html").read_text(encoding="utf-8"), encoding="utf-8")
        rows.append((run.name, d))
    items = "".join(
        f'<li><a href="{html.escape(n)}/">{html.escape(d["passage"]["title"])}</a>'
        f'<span>{html.escape(", ".join(r["name"] for r in d["readers"]))}</span>'
        f'<small>{html.escape(n)} · {len(d["comments"])} comments · {d["layers_done"]} rounds · {html.escape(d.get("started", "")[:10])}</small></li>'
        for n, d in rows)
    (docs / "index.html").write_text(HEAD + (TEMPLATES / "index.html").read_text(encoding="utf-8").replace("<!--RUNS-->", items), encoding="utf-8")
    print(f"{len(rows)} page(s) -> {docs}")
