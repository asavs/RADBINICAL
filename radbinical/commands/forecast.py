"""Report a run's forecasts: how well readers predicted which comments would draw replies.

    python -m radbinical forecast runs/<dir>
    python -m radbinical forecast runs/<dir> --rescore    # recompute the scores from page.json

Forecasts are made during rounds when the page's `forecast` flag is on; they live in
forecasts.json. Precision is the share of named comments that drew a reply from someone other
than their author; chance is the precision of naming the same number at random. "self" counts
hits the forecaster brought about by replying itself.
"""
import argparse
import sys

from ..forecast import rescore, summary
from ..page import Page


def _f(x):
    return "   -" if x is None else f"{x:.2f}"


def table(title, groups):
    print(f"\n{title:<24} {'fcasts':>6} {'errors':>6} {'named':>5} {'hits':>4} {'self':>4} "
          f"{'prec':>5} {'pooled':>6} {'chance':>6} {'recall':>6}")
    for k, g in groups.items():
        print(f"{str(k):<24} {g['forecasts']:>6} {g['errors']:>6} {g['named']:>5} {g['hits']:>4} {g['self']:>4} "
              f"{_f(g['precision']):>5} {_f(g['pooled_precision']):>6} {_f(g['chance']):>6} {_f(g['recall']):>6}")


def main(a):
    page = Page.load(a.run)
    side = rescore(page) if a.rescore else page.side("forecasts")
    if not side or not side.get("forecasts"):
        sys.exit(f"no forecasts in {page.dir}; run rounds with the flag \"forecast\": true")
    fs = side["forecasts"]
    print(f"{len(fs)} forecasts in {page.dir / 'forecasts.json'}" + (" (rescored)" if a.rescore else ""))
    table("reader", summary(fs, "reader"))
    table("round", summary(fs, "round"))
    print("\nprec and chance are means over forecasts; pooled is all hits over all comments named.")
    for f in fs:
        if "error" in f:
            print(f"  round {f['round']} {f['reader']}: ERROR {f['error'][:160]}")


def register(sub):
    p = sub.add_parser("forecast", help="report how well readers predicted replies", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run")
    p.add_argument("--rescore", action="store_true", help="recompute every score from page.json and save")
    p.set_defaults(f=main)
