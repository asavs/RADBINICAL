"""Add rounds to an existing page, optionally with new readers joining.

    python -m radbinical extend runs/<dir> -n 2
    python -m radbinical extend runs/<dir> -n 1 --models x-ai/grok-4.7
    python -m radbinical extend runs/<dir> -n 1 --models qwen/qwen3.8-27b --only-new

New readers change the page's `cast`; its `group` stays. With --only-new, only the readers that
--models adds take the added rounds; the others sit them out. --sit-out names readers who skip the added rounds. --max-tokens sets the output limit of the readers --models adds.

Before the rounds start, every reader who will take them is asked for one word (see `check`); if
one cannot be reached, nothing is run and the page is left as it was. --no-check skips that.
"""
import argparse
import sys

from ..page import Page, cast_of, models_of, reader_entry, taking_turns
from ..preflight import require
from ..rounds import run_layers


def main(a):
    page = Page.load(a.run)
    new = set()
    if a.models:
        have = {r["name"] for r in page.d["readers"]}
        for m in a.models.split(","):
            r = reader_entry(m.strip())
            if a.max_tokens:
                r["max_tokens"] = a.max_tokens
            if r["name"] not in have:
                page.d["readers"].append(r)
                have.add(r["name"])
                new.add(r["name"])
        page.d["cast"] = cast_of(page.d["readers"])
    if a.only_new and not new:
        sys.exit("--only-new needs --models naming at least one reader not already on the page")
    sit_out = [s.strip() for s in (a.sit_out or "").split(",") if s.strip()]
    who = taking_turns(page.d, sit_out, new if a.only_new else None)
    if not a.no_check:
        require([r for r in models_of(page.d) if who is None or r["name"] in who], page.d["flags"])
    page.d.pop("at_rest", None)
    ok = run_layers(page, a.n, who)
    print(f"\n{len(page.d['comments'])} comments over {page.d['layers_done']} round(s)\n{page.dir / 'page.html'}")
    sys.exit(0 if ok else 1)


def register(sub):
    p = sub.add_parser("extend", help="add rounds to an existing page", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run")
    p.add_argument("-n", type=int, default=1, help="rounds to add")
    p.add_argument("--models", help="comma-separated extra readers who join the existing page")
    p.add_argument("--only-new", action="store_true", help="only the readers --models adds take the added rounds")
    p.add_argument("--max-tokens", type=int, help="output limit per call for the readers --models adds")
    p.add_argument("--sit-out", help="comma-separated names of readers who skip the added rounds")
    p.add_argument("--no-check", action="store_true", help="start without first asking every reader for one word")
    p.set_defaults(f=main)
