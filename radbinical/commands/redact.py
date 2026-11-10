"""Have models compile a page into what is disputed, settled and unresolved, then check them.

    python -m radbinical redact runs/<dir> --models a,b,c [--signed | --unsigned]
    python -m radbinical redact check runs/<dir> --judge <model>
    python -m radbinical redact compare runs/<dir>

The first form has each model read the whole page and report its state without ruling on it,
citing comment ids and quoting comments; a model already in redactions.json is replaced. Cited
ids and quotes are checked against the page at once. Authors are named or shown as "Reader A",
"Reader B", ... as the page's `signed` flag says, unless --signed or --unsigned overrides it.

`check` has a judge rate each item against the comments it cites: supported, distorted or
unsupported. `compare` prints the overlap between the models' redactions by cited ids.
Everything is stored in runs/<dir>/redactions.json.
"""
import argparse
import sys

from ..page import Page
from ..redact import judge_items, load, redact, report, save

ACTIONS = ("check", "compare")


def main(a):
    action, run = (a.first, a.run) if a.first in ACTIONS else ("compile", a.first)
    if not run or (a.run and action == "compile"):
        sys.exit("usage: redact runs/<dir> --models a,b  |  redact check runs/<dir> --judge m  |  redact compare runs/<dir>")
    page = Page.load(run)
    if action == "compile":
        models = [m.strip() for m in (a.models or "").split(",") if m.strip()]
        if not models:
            sys.exit("redact needs --models a,b,c")
        side = redact(page, models, a.signed)
    elif action == "check":
        if not a.judge:
            sys.exit("redact check needs --judge <model>")
        if not load(page)["redactions"]:
            sys.exit(f"no redactions in {run}; run `redact {run} --models ...` first")
        side = judge_items(page, a.judge)
    else:
        side = load(page)
        save(page, side)
    print(report(side))
    print(f"\n{page.dir / 'redactions.json'}")
    if action == "compile" and all(r.get("error") for r in side["redactions"] if r["model"] in models):
        sys.exit(1)


def register(sub):
    p = sub.add_parser("redact", help="compile a page into disputed, settled and unresolved; check and compare",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("first", metavar="[check|compare] run", help="the run folder, or check / compare followed by it")
    p.add_argument("run", nargs="?", help=argparse.SUPPRESS)
    p.add_argument("--models", help="comma-separated models that each write a redaction")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--signed", dest="signed", action="store_const", const=True, help="name the authors")
    g.add_argument("--unsigned", dest="signed", action="store_const", const=False, help='show authors as "Reader A", ...')
    p.add_argument("--judge", help="model that rates each item (for check)")
    p.set_defaults(f=main, signed=None)
