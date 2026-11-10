"""Command line.

    python3 -m radbinical run config.json            # start a new page
    python3 -m radbinical extend runs/<dir> -n 2     # add rounds to an existing page
    python3 -m radbinical extend runs/<dir> -n 1 --models x-ai/grok-4.7
    python3 -m radbinical render runs/<dir>          # rebuild page.html
    python3 -m radbinical site                       # rebuild docs/ for the website
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from .config import DEFAULT_FLAGS, ROOT, load_dotenv
from .page import Page, load_passage
from .prompts import system_prompt
from .providers import split_model
from .rounds import run_layers
from .site import build_site, render


def reader_entry(m):
    if isinstance(m, str):
        m = {"model": m}
    name = m.get("name") or split_model(m["model"])[1].split("/")[-1]
    return {**{k: m[k] for k in ("protocol", "max_tokens") if k in m}, "model": m["model"], "name": name}


def cmd_run(a):
    cfg = json.loads(Path(a.config).read_text())
    flags = {**DEFAULT_FLAGS, **cfg.get("flags", {})}
    unknown = set(flags) - set(DEFAULT_FLAGS)
    if unknown:
        sys.exit(f"unknown flag(s) in config: {', '.join(sorted(unknown))}")
    base = Path(a.config).resolve().parent
    p = cfg["passage"]
    text = load_passage(base / p["file"])
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", p["title"].lower()).strip("-")[:40]
    out = Path(a.out) if a.out else ROOT / "runs" / f"{stamp}-{slug}"
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "passage": {"title": p["title"], "source": p.get("source", ""), "text": text},
        "readers": [reader_entry(m) for m in cfg["models"]],
        "flags": flags, "comments": [], "log": [], "counter": 0, "layers_done": 0,
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    names = [r["name"] for r in data["readers"]]
    if len(set(names)) != len(names):
        sys.exit("reader names must be unique; give duplicates a distinct \"name\" in the config")
    page = Page(data, out)
    data["prompt_example"] = system_prompt(data, names[0], lambda x: x)
    page.save()
    ok = run_layers(page, flags["max_layers"])
    print(f"\n{len(data['comments'])} comments over {data['layers_done']} round(s)\n{out / 'page.html'}")
    sys.exit(0 if ok else 1)


def cmd_extend(a):
    out = Path(a.run)
    page = Page(json.loads((out / "page.json").read_text()), out)
    if a.models:
        have = {r["name"] for r in page.d["readers"]}
        for m in a.models.split(","):
            r = reader_entry(m.strip())
            if r["name"] not in have:
                page.d["readers"].append(r)
    page.d.pop("at_rest", None)
    ok = run_layers(page, a.n)
    print(f"\n{len(page.d['comments'])} comments over {page.d['layers_done']} round(s)\n{out / 'page.html'}")
    sys.exit(0 if ok else 1)


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(prog="radbinical", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("config"); r.add_argument("--out"); r.set_defaults(f=cmd_run)
    e = sub.add_parser("extend"); e.add_argument("run"); e.add_argument("-n", type=int, default=1)
    e.add_argument("--models", help="comma-separated extra readers who join the existing page"); e.set_defaults(f=cmd_extend)
    v = sub.add_parser("render"); v.add_argument("run"); v.set_defaults(f=lambda a: (render(a.run), print(Path(a.run) / "page.html")))
    sub.add_parser("site").set_defaults(f=lambda a: build_site())
    a = ap.parse_args()
    a.f(a)
