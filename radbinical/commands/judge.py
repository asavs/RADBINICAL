"""Judge a page with a model: were the planted comments caught, and are hedged claims more often wrong?

    python -m radbinical judge plants runs/<dir> --judge anthropic:claude-opus-5-5
    python -m radbinical judge claims runs/<dir> --judge anthropic:claude-opus-5-5 --extract qwen/qwen3.8-27b

`plants` reads every comment that replies to a plant (at any depth) or names it in see_also, and
has the judge say whether each one catches, accepts, ignores or dismisses it. Writes plants.json.

`claims` has the extractor (default: the judge) pull checkable factual claims out of the readers'
own comments, marking each hedged or not, then has the judge rate each claim, shown alone, right,
wrong or unsure. Writes claims.json and prints the wrong rate for hedged against unhedged claims.
"""
import argparse

from ..judge import claims_report, judge_claims, judge_plants, plants_report
from ..page import Page


def plants(a):
    page = Page.load(a.run)
    res = judge_plants(page.d, a.judge)
    page.save_side("plants", res)
    print(plants_report(res) + f"\n{page.dir / 'plants.json'}")


def claims(a):
    page = Page.load(a.run)
    res = judge_claims(page.d, a.judge, a.extract)
    page.save_side("claims", res)
    print(claims_report(res) + f"\n{page.dir / 'claims.json'}")


def register(sub):
    p = sub.add_parser("judge", help="judge plants or factual claims on a page", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="what", required=True, metavar="<plants|claims>")
    q = s.add_parser("plants", help="were the planted comments caught or dismissed")
    q.add_argument("run")
    q.add_argument("--judge", required=True, help="model id, routed as a reader's is")
    q.set_defaults(f=plants)
    q = s.add_parser("claims", help="error rate of hedged against unhedged factual claims")
    q.add_argument("run")
    q.add_argument("--judge", required=True, help="model that rates each claim")
    q.add_argument("--extract", help="model that pulls claims out of comments (default: the judge)")
    q.set_defaults(f=claims)
