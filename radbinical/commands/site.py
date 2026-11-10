"""Rebuild docs/ for the website: every run under runs/ plus an index.

    python -m radbinical site
    python -m radbinical site --runs some/runs --out some/docs
"""
import argparse

from ..site import build_site


def register(sub):
    p = sub.add_parser("site", help="rebuild docs/ for the website", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", help="folder of runs (default runs/)")
    p.add_argument("--out", help="folder to write the site into (default docs/)")
    p.set_defaults(f=lambda a: build_site(a.runs, a.out))
