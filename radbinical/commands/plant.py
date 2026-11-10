"""Insert a planted comment under an existing model reader's name, to see whether later rounds catch it.

    python -m radbinical plant runs/<dir> --as gpt-6.1-sol --sort slip --target passage \\
        --quote "a matter of human institution solely" \\
        --text "As Mill says in the 1859 first edition, ..." \\
        --truth "The Principles first appeared in 1848, not 1859."
    python -m radbinical plant runs/<dir> --file plants.json

Sort "slip" is a subtle factual slip or bad argument; --truth says what is wrong with it. Sort
"sound" is a sound but unfashionable reading; --truth says why it holds. --target is "passage"
(then --quote is required, the exact words it attaches to) or a comment id such as c7.

The comment reads as written in round --round, by default the last finished round, so the next
`extend` rounds can answer it. It is stored with kind "plant" and meta {"sort", "truth"}, which
readers never see. --file takes a JSON list of objects with the same keys: "as", "sort",
"target", "quote", "text", "truth", "round" and optionally "see_also". Every plant is checked
before any is saved; if one fails, nothing is written.
"""
import argparse
import json
import sys
from pathlib import Path

from ..page import Page, models_of
from ..site import render

SORTS = ("slip", "sound")


def add_plant(page, p):
    """Validate and record one plant dict on a loaded Page. Returns (ok, message)."""
    d = page.d
    who, sort, truth = p.get("as"), p.get("sort"), str(p.get("truth") or "").strip()
    names = [r["name"] for r in models_of(d)]
    if who not in names:
        return False, f"no model reader named {who!r}; the model readers are {', '.join(names)}"
    if sort not in SORTS:
        return False, f"sort must be one of {', '.join(SORTS)}, not {sort!r}"
    if not truth:
        return False, "truth is empty: say what is wrong with a slip, or why a sound reading holds"
    last = max(1, d["layers_done"])
    rnd = p.get("round")
    rnd = last if rnd is None else rnd
    if not isinstance(rnd, int) or not 1 <= rnd <= last:
        return False, f"round must be between 1 and {last}, not {rnd!r}"
    args = {k: p[k] for k in ("target", "quote", "text", "see_also") if p.get(k) is not None}
    ok, msg = page.add(who, rnd, args, kind="plant", meta={"sort": sort, "truth": truth})
    return ok, (msg if ok else msg.removeprefix("Not recorded: "))


def main(a):
    if a.file:
        plants = json.loads(Path(a.file).read_text(encoding="utf-8"))
        if isinstance(plants, dict):
            plants = [plants]
        if not isinstance(plants, list) or not all(isinstance(p, dict) for p in plants):
            sys.exit("--file must hold a JSON list of plant objects")
    else:
        plant = {"as": a.author, "sort": a.sort, "target": a.target, "quote": a.quote, "text": a.text,
                 "truth": a.truth, "round": a.round}
        missing = [f"--{k}" for k in ("as", "sort", "target", "text", "truth") if plant[k] is None]
        if missing:
            sys.exit(f"missing {', '.join(missing)} (or give --file)")
        plants = [plant]
    page = Page.load(a.run)
    errors, made = [], []
    for i, p in enumerate(plants, 1):
        ok, msg = add_plant(page, p)
        (made if ok else errors).append(f"plant {i}: {msg}")
    if errors:
        sys.exit("nothing saved:\n" + "\n".join(errors))
    page.save()
    render(page.dir)
    print("\n".join(made) + f"\n{page.dir / 'page.html'}")


def register(sub):
    p = sub.add_parser("plant", help="insert a planted comment under a reader's name", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run")
    p.add_argument("--as", dest="author", metavar="READER", help="name of an existing reader")
    p.add_argument("--sort", choices=SORTS)
    p.add_argument("--target", help='"passage" or a comment id')
    p.add_argument("--quote", help="exact words the comment attaches to")
    p.add_argument("--text", help="the comment as readers will see it")
    p.add_argument("--truth", help="what is wrong with it (slip) or why it holds (sound)")
    p.add_argument("--round", type=int, help="round it is filed under (default: the last finished round)")
    p.add_argument("--file", help="JSON list of plants instead of the options above")
    p.set_defaults(f=main)
