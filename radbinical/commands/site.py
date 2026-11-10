"""Rebuild docs/ for the website: every run under runs/ plus an index.

    python -m radbinical site
"""
import argparse

from ..site import build_site


def register(sub):
    p = sub.add_parser("site", help="rebuild docs/ for the website", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.set_defaults(f=lambda a: build_site())
