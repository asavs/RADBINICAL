"""Have models rule on hypothetical cases, with the bare passage and with the page as precedent.

    python -m radbinical caselaw runs/<dir>
    python -m radbinical caselaw runs/<dir> --cases cases/mill-property.json --models a,b,c --repeat 3
    python -m radbinical caselaw runs/<dir> --report        # reprint from rulings.json, no calls

The cases file defaults to cases/<passage id>.json and the models to the page's model readers. Each
model rules on each case under "bare" (the passage only) and "page" (passage and margins, citing
comments by id). Writes rulings.json and prints agreement between models per condition,
self-consistency across repeats, the most cited comments and how many rulings changed.
Agreement going up with the page shows the page made rulings more consistent, not more correct.
"""
import argparse
import sys

from ..caselaw import load_cases, report, run, summarize
from ..config import ROOT
from ..page import Page, models_of, reader_entry


def main(a):
    page = Page.load(a.run)
    if a.report:
        side = page.side("rulings")
        if not side:
            sys.exit(f"no rulings.json in {page.dir}")
        side["summary"] = summarize(side["cases"], side["rulings"])
        page.save_side("rulings", side)
        print(report(side["cases"], side["summary"], max((r["rep"] for r in side["rulings"]), default=0) + 1))
        return
    path = a.cases or ROOT / "cases" / f"{page.d['passage'].get('id', '')}.json"
    try:
        cases = load_cases(path)
    except (OSError, ValueError) as e:
        sys.exit(f"cannot use cases file: {e}")
    if a.models:
        models = [(r["model"], r["name"]) for r in (reader_entry(m.strip()) for m in a.models.split(",") if m.strip())]
    else:
        models = [(r["model"], r["name"]) for r in models_of(page.d)]
    if a.repeat < 1:
        sys.exit("--repeat takes 1 or more")
    n = len(cases) * len(models) * 2 * a.repeat
    print(f"{len(cases)} cases x {len(models)} models x 2 conditions x {a.repeat} = {n} rulings", flush=True)
    rulings, usage = run(page, cases, models, a.repeat, a.workers, a.temperature)
    summary = summarize(cases, rulings)
    page.save_side("rulings", {"cases": cases, "rulings": rulings, "summary": summary, "usage": usage})
    print(report(cases, summary, a.repeat))
    print(f"\n{page.dir / 'rulings.json'}")


def register(sub):
    p = sub.add_parser("caselaw", help="rule on hypothetical cases with and without the page", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run")
    p.add_argument("--cases", help="cases file (default cases/<passage id>.json)")
    p.add_argument("--models", help="comma-separated models (default: the page's readers)")
    p.add_argument("--repeat", type=int, default=1, help="ask each (model, case, condition) this many times")
    p.add_argument("--workers", type=int, default=8, help="calls at once")
    p.add_argument("--temperature", type=float, help="sampling temperature for every ruling")
    p.add_argument("--report", action="store_true", help="recompute and print the summary from rulings.json")
    p.set_defaults(f=main)
