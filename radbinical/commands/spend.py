"""What the runs cost: per run and in total, the cost providers reported, the cost estimated
from tokens (radbinical/prices.py) and their sum, over each page's log.

    python -m radbinical spend
    python -m radbinical spend --since 2026-11-10            # runs started at or after this
    python -m radbinical spend --since 2026-11-10T01:00 --runs some/runs

The last line is the grand total, as `total <number> USD`.
"""
import argparse
import datetime

from ..prices import costs
from ..table import page_of, run_dirs, usages


def when(s):
    return datetime.datetime.fromisoformat(s).replace(tzinfo=None)


def main(a):
    since = when(a.since) if a.since else None
    rows = []
    for d in run_dirs(a.runs):
        page = page_of(d)
        started = page.get("started")
        if since and not (started and when(started) >= since):
            continue
        rows.append((d.name, started or "", *costs(usages(page))))
    w = max([len(r[0]) for r in rows] + [3])
    print(f"{'run':<{w}}  {'started':<19}  {'reported':>10}  {'estimated':>10}  {'sum':>10}")
    for name, started, rep, est in rows:
        print(f"{name:<{w}}  {started:<19}  {rep:10.4f}  {est:10.4f}  {rep + est:10.4f}")
    rep, est = sum(r[2] for r in rows), sum(r[3] for r in rows)
    print(f"{len(rows)} run(s): reported {rep:.4f}, estimated {est:.4f} USD")
    print(f"total {rep + est:.4f} USD")


def register(sub):
    p = sub.add_parser("spend", help="cost reported and estimated, per run and in total", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", help="folder of runs (default runs/)")
    p.add_argument("--since", help="only runs whose `started` is at or after this ISO date or date and time")
    p.set_defaults(f=main)
