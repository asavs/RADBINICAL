"""Rebuild a run's page.html from its page.json.

    python -m radbinical render runs/<dir>
"""
import argparse
from pathlib import Path

from ..site import render


def main(a):
    render(a.run)
    print(Path(a.run) / "page.html")


def register(sub):
    p = sub.add_parser("render", help="rebuild a run's page.html", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run")
    p.set_defaults(f=main)
