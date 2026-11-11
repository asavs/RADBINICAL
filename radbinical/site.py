"""Turning a run's record into a web page, and all runs into a website."""
import html
import json
import re
from pathlib import Path

from .config import PACKAGE, ROOT, TEMPLATES
from .providers import KNOWN
from .table import run_dirs


HEAD = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n'


ICONS = "https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.101.0/icons/"
REPO = "https://github.com/asavs/RADBINICAL"
WORKFLOW = REPO + "/actions/workflows/run.yml"   # the Run workflow; only the owner can start it


def load_brands():
    return json.loads((PACKAGE / "brands.json").read_text(encoding="utf-8"))


def brand_of(reader, brands):
    """The maker's entry in brands.json for a reader, or None."""
    head, sep, rest = reader["model"].partition(":")
    ident = rest if sep and head in KNOWN else reader["model"]
    vendor = ident.split("/")[0] if "/" in ident else (head if head in KNOWN else "")
    return brands.get(reader.get("brand") or vendor)


def marks(readers, brands):
    """Small logo strip for the index: one mark per distinct maker, in reader order."""
    out, seen = [], set()
    for r in readers:
        b = brand_of(r, brands)
        if not b or b["icon"] in seen:
            continue
        seen.add(b["icon"])
        url, name = ICONS + b["icon"] + ".svg", html.escape(b["name"])
        flip = ' class="flip"' if b.get("flip") else ""
        out.append(f'<img{flip} src="{url}" alt="{name}" title="{name}">' if b["icon"].endswith("-color")
                   else f'<i role="img" aria-label="{name}" title="{name}" style="--u:url({url})"></i>')
    return f'<span class="marks">{"".join(out)}</span>' if out else ""


def render(run_dir):
    """Write page.html beside page.json."""
    run_dir = Path(run_dir)
    data = json.loads((run_dir / "page.json").read_text(encoding="utf-8"))
    data["site"] = {"run": run_dir.name, "workflow": WORKFLOW}
    tpl = (TEMPLATES / "viewer.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    title = "Marginalia on " + re.sub(r"[<>&]", "", data["passage"]["title"])
    brands = json.dumps({k: v for k, v in load_brands().items() if not k.startswith("_")})
    kernel = (TEMPLATES / "kernel.js").read_text(encoding="utf-8")
    html = (tpl.replace("__TITLE__", title).replace("/*__KERNEL__*/", kernel)
            .replace("/*__PAGE_DATA__*/null", blob).replace("/*__BRANDS__*/{}", brands))
    (run_dir / "page.html").write_text(html, encoding="utf-8")


def _stats(d):
    return f'{len(d["comments"])} comments · {d["layers_done"]} rounds'


def index_items(rows, brands):
    """The index list from [(run name, page)]. Repeats of one config share an entry."""
    groups = {}
    for n, d in rows:
        groups.setdefault(d.get("group") or n, []).append((n, d))
    out = []
    for g, members in groups.items():
        n, d = members[0]
        head = (f'<li><a href="{html.escape(n)}/">{html.escape(d["passage"]["title"])}</a>{marks(d["readers"], brands)}'
                f'<span>{html.escape(", ".join(r["name"] for r in d["readers"]))}</span>')
        date = html.escape(d.get("started", "")[:10])
        if len(members) == 1:
            out.append(f'{head}<small>{html.escape(n)} · {_stats(d)} · {date}</small></li>')
            continue
        runs = " · ".join(f'<a href="{html.escape(m)}/">{html.escape(m)}</a> {_stats(e)}' for m, e in members)
        out.append(f'{head}<small>{html.escape(g)} · run {len(members)} times · {date}</small><small>{runs}</small></li>')
    return "".join(out)


def build_site(runs_dir=None, out=None):
    """Build a static site (default docs/) from the runs under runs_dir (default runs/): one page
    per run plus an index."""
    docs = Path(out) if out else ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / ".nojekyll").write_text("", encoding="utf-8")
    rows = []
    for run in run_dirs(runs_dir):
        render(run)
        d = json.loads((run / "page.json").read_text(encoding="utf-8"))
        (docs / run.name).mkdir(parents=True, exist_ok=True)
        (docs / run.name / "index.html").write_text(HEAD + (run / "page.html").read_text(encoding="utf-8"), encoding="utf-8")
        rows.append((run.name, d))
    items = index_items(rows, load_brands())
    (docs / "index.html").write_text(HEAD + (TEMPLATES / "index.html").read_text(encoding="utf-8").replace("<!--RUNS-->", items), encoding="utf-8")
    print(f"{len(rows)} page(s) -> {docs}")
