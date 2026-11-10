"""Turning a run's record into a web page, and all runs into a website."""
import html
import json
import re
from pathlib import Path

from .config import PACKAGE, ROOT, TEMPLATES


HEAD = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n'


ICONS = "https://cdn.jsdelivr.net/npm/@lobehub/icons-static-svg@1.101.0/icons/"
PREFIXES = ("openrouter", "openai", "nvidia", "anthropic", "mock")


def load_brands():
    return json.loads((PACKAGE / "brands.json").read_text(encoding="utf-8"))


def brand_of(reader, brands):
    """The maker's entry in brands.json for a reader, or None."""
    head, sep, rest = reader["model"].partition(":")
    ident = rest if sep and head in PREFIXES else reader["model"]
    vendor = ident.split("/")[0] if "/" in ident else (head if head in PREFIXES else "")
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
    run_dir = Path(run_dir)
    data = json.loads((run_dir / "page.json").read_text())
    tpl = (TEMPLATES / "viewer.html").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    title = "Marginalia on " + re.sub(r"[<>&]", "", data["passage"]["title"])
    brands = json.dumps({k: v for k, v in load_brands().items() if not k.startswith("_")})
    html = tpl.replace("__TITLE__", title).replace("/*__PAGE_DATA__*/null", blob).replace("/*__BRANDS__*/{}", brands)
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
    brands = load_brands()
    items = "".join(
        f'<li><a href="{html.escape(n)}/">{html.escape(d["passage"]["title"])}</a>'
        f'{marks(d["readers"], brands)}'
        f'<span>{html.escape(", ".join(r["name"] for r in d["readers"]))}</span>'
        f'<small>{html.escape(n)} · {len(d["comments"])} comments · {d["layers_done"]} rounds · {html.escape(d.get("started", "")[:10])}</small></li>'
        for n, d in rows)
    (docs / "index.html").write_text(HEAD + (TEMPLATES / "index.html").read_text(encoding="utf-8").replace("<!--RUNS-->", items), encoding="utf-8")
    print(f"{len(rows)} page(s) -> {docs}")
