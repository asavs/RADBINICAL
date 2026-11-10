"""Copy a page into separate lineages that go on without seeing each other.

    python -m radbinical fork runs/<dir> --into 3                  # runs/<dir>-s1, -s2, -s3
    python -m radbinical fork runs/<dir> --into 3 -n 2             # then two rounds on each copy
    python -m radbinical fork runs/<dir> --into 2 -n 1 --models x-ai/grok-4.7 --unsigned

Each copy is the page as it stands: page.json, plus the side files in CARRIED (the record of
the page's own text, such as amendments.json). Side files that judge or summarise the source
page (redactions, plants, claims, rulings, forecasts) stay with the source; the copy will grow
past what they describe.

A copy carries `lineage` (the source run's folder name), `group` (its own folder name), its own
`seed` (the source's seed plus its number) and `forked_from` {"run", "round", "comments"}, where
"comments" is the source's comment counter at the fork: comments numbered up to it are the
source's, copied (the table marks them `inherited`). The usage of the
calls that built the page so far is left with the source, so a run's cost counts only its own
calls: copied log entries lose `usage` and gain `from`, and carried side files start an empty
`usage` list.

With -n, every copy is extended that many rounds, the copies concurrently. --models adds readers
to every copy (as extend --models does); --unsigned shows readers to each other as "Reader A",
"Reader B" in the copies.
"""
import argparse
import concurrent.futures as cf
import copy
import sys
from pathlib import Path

from ..page import Page, cast_of, reader_entry
from ..prompts import system_prompt
from ..rounds import run_layers
from ..site import render

CARRIED = ("amendments",)


def fork(src, into, rounds=0, models=None, unsigned=False):
    """Write `into` copies of the run at `src`; extend each `rounds` rounds. Returns [(Page, ok)]."""
    src = Path(src)
    if into < 1:
        sys.exit("--into takes 1 or more")
    source = Page.load(src)
    dirs = [src.with_name(f"{src.name}-s{i}") for i in range(1, into + 1)]
    taken = [d.name for d in dirs if d.exists()]
    if taken:
        sys.exit(f"already exists: {', '.join(taken)}")
    pages = []
    for i, d in enumerate(dirs, 1):
        data = copy.deepcopy(source.d)
        data["lineage"], data["group"] = src.name, d.name
        data["forked_from"] = {"run": src.name, "round": data["layers_done"], "comments": data["counter"]}
        data["flags"]["seed"] = data["flags"]["seed"] + i
        for e in data["log"]:
            e.pop("usage", None)
            e.setdefault("from", src.name)
        if models:
            have = {r["name"] for r in data["readers"]}
            for m in models.split(","):
                r = reader_entry(m.strip())
                if r["name"] not in have:
                    data["readers"].append(r)
                    have.add(r["name"])
            data["cast"] = cast_of(data["readers"])
        if unsigned:
            data["flags"]["signed"] = False
        if data["readers"]:
            data["prompt_example"] = system_prompt(data, data["readers"][0]["name"], lambda x: x)
        d.mkdir(parents=True)
        page = Page(data, d)
        page.save()
        for name in CARRIED:
            side = source.side(name)
            if side is not None:
                if isinstance(side, dict):
                    side = {**side, "usage": []}
                page.save_side(name, side)
        render(d)
        pages.append(page)
        print(f"{d.name}: seed {data['flags']['seed']}, from round {data['forked_from']['round']} of {src.name}", flush=True)
    if rounds <= 0:
        return [(p, True) for p in pages]

    def extend(page):
        page.d.pop("at_rest", None)
        return run_layers(page, rounds)

    with cf.ThreadPoolExecutor(len(pages)) as ex:
        oks = list(ex.map(extend, pages))
    return list(zip(pages, oks))


def main(a):
    done = fork(a.run, a.into, a.n, a.models, a.unsigned)
    for page, _ in done:
        print(f"{page.dir.name}: {len(page.d['comments'])} comments over {page.d['layers_done']} round(s)")
    sys.exit(0 if all(ok for _, ok in done) else 1)


def register(sub):
    p = sub.add_parser("fork", help="copy a page into lineages that go on separately", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run")
    p.add_argument("--into", type=int, required=True, help="number of copies, written as <run>-s1, <run>-s2, ...")
    p.add_argument("-n", type=int, default=0, help="rounds to add to each copy (default none)")
    p.add_argument("--models", help="comma-separated extra readers who join every copy")
    p.add_argument("--unsigned", action="store_true", help="hide reader names from each other in the copies")
    p.set_defaults(f=main)
