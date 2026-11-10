"""Refresh radbinical/prices.json from OpenRouter's public model list (no key needed).

    python -m radbinical prices
    python -m radbinical prices --out some/prices.json

Keeps every model with a non-zero price per prompt or completion token, in USD per token. The
snapshot prices calls whose provider reports tokens but no cost (see radbinical/prices.py).
"""
import argparse
import datetime
import json
import urllib.request
from pathlib import Path

from .. import prices


def fetch():
    req = urllib.request.Request(prices.SOURCE, headers={"User-Agent": "radbinical", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main(a):
    models = prices.from_listing(fetch())
    if not models:
        raise SystemExit("OpenRouter's model list had no priced models; prices.json left as it was")
    out = Path(a.out) if a.out else prices.FILE
    out.write_text(prices.snapshot_text(models, datetime.date.today().isoformat()), encoding="utf-8")
    print(f"{len(models)} priced models -> {out}")


def register(sub):
    p = sub.add_parser("prices", help="refresh the token prices used to estimate cost", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", help="file to write (default radbinical/prices.json)")
    p.set_defaults(f=main)
