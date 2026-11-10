"""Start a new page from a config.

    python -m radbinical run config.json
    python -m radbinical run config.json --out runs/mill-03
    python -m radbinical run config.json --repeat 3 --out runs/mill-cast1   # mill-cast1-a, -b, -c

Repeats share one `group` (the name given by --out, or the generated one) and take seeds
seed, seed+1, ... from the config's `seed` flag. Without --repeat, `group` is the folder name.

Before anything is started, every reader is asked for one word (see `check`); if one cannot be
reached, nothing is run. --no-check skips that.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

from ..config import DEFAULT_FLAGS, ROOT
from ..page import Page, cast_of, load_passage, reader_entry
from ..preflight import require
from ..prompts import system_prompt
from ..rounds import run_layers


def new_page(cfg, base, out, group, seed=None):
    """Create the folder and page.json for one run of a config; returns the Page, not yet run."""
    flags = {**DEFAULT_FLAGS, **cfg.get("flags", {})}
    unknown = set(flags) - set(DEFAULT_FLAGS)
    if unknown:
        sys.exit(f"unknown flag(s) in config: {', '.join(sorted(unknown))}")
    if seed is not None:
        flags["seed"] = seed
    p = cfg["passage"]
    readers = [reader_entry(m) for m in cfg["models"]]
    names = [r["name"] for r in readers]
    if len(set(names)) != len(names):
        sys.exit("reader names must be unique; give duplicates a distinct \"name\" in the config")
    data = {
        "passage": {"id": Path(p["file"]).stem, "title": p["title"], "source": p.get("source", ""),
                    "text": load_passage(base / p["file"])},
        "readers": readers, "cast": cast_of(readers), "group": group,
        "flags": flags, "comments": [], "log": [], "counter": 0, "layers_done": 0,
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    page = Page(data, out)
    data["prompt_example"] = system_prompt(data, names[0], lambda x: x)
    page.save()
    return page


def run_config(config, out=None, repeat=1, check=True):
    """Run a config `repeat` times. Returns [(run folder, ok)]. Unless `check` is off, nothing is
    started until every reader has answered a one-word request."""
    config = Path(config)
    cfg = json.loads(config.read_text(encoding="utf-8"))
    if not 1 <= repeat <= 26:
        sys.exit("--repeat takes 1 to 26")
    if check:
        require([reader_entry(m) for m in cfg["models"]], {**DEFAULT_FLAGS, **cfg.get("flags", {})})
    if out:
        out = Path(out)
    else:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", cfg["passage"]["title"].lower()).strip("-")[:40]
        out = ROOT / "runs" / f"{stamp}-{slug}"
    seed = cfg.get("flags", {}).get("seed", DEFAULT_FLAGS["seed"])
    dirs = [out] if repeat == 1 else [out.with_name(f"{out.name}-{chr(97 + i)}") for i in range(repeat)]
    done = []
    for i, d in enumerate(dirs):
        page = new_page(cfg, config.resolve().parent, d, out.name, seed + i)
        if repeat > 1:
            print(f"== {d.name} (seed {seed + i})", flush=True)
        ok = run_layers(page, page.d["flags"]["max_layers"])
        print(f"\n{len(page.d['comments'])} comments over {page.d['layers_done']} round(s)\n{d / 'page.html'}")
        done.append((d, ok))
    return done


def main(a):
    done = run_config(a.config, a.out, a.repeat, not a.no_check)
    sys.exit(0 if all(ok for _, ok in done) else 1)


def register(sub):
    p = sub.add_parser("run", help="start a new page from a config", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("config")
    p.add_argument("--out", help="run folder (with --repeat, the stem of each folder and the group name)")
    p.add_argument("--repeat", type=int, default=1, help="run the config this many times, as <out>-a, <out>-b, ...")
    p.add_argument("--no-check", action="store_true", help="start without first asking every reader for one word")
    p.set_defaults(f=main)
