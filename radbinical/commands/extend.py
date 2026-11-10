"""Add rounds to an existing page, optionally with new readers joining.

    python -m radbinical extend runs/<dir> -n 2
    python -m radbinical extend runs/<dir> -n 1 --models x-ai/grok-4.7

New readers change the page's `cast`; its `group` stays.
"""
import argparse
import sys

from ..page import Page, cast_of, reader_entry
from ..rounds import run_layers


def main(a):
    page = Page.load(a.run)
    if a.models:
        have = {r["name"] for r in page.d["readers"]}
        for m in a.models.split(","):
            r = reader_entry(m.strip())
            if r["name"] not in have:
                page.d["readers"].append(r)
        page.d["cast"] = cast_of(page.d["readers"])
    page.d.pop("at_rest", None)
    ok = run_layers(page, a.n)
    print(f"\n{len(page.d['comments'])} comments over {page.d['layers_done']} round(s)\n{page.dir / 'page.html'}")
    sys.exit(0 if ok else 1)


def register(sub):
    p = sub.add_parser("extend", help="add rounds to an existing page", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run")
    p.add_argument("-n", type=int, default=1, help="rounds to add")
    p.add_argument("--models", help="comma-separated extra readers who join the existing page")
    p.set_defaults(f=main)
