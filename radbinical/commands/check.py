"""Ask each model reader of a config or a run for one word, to see that it can be reached.

    python -m radbinical check config.json
    python -m radbinical check runs/<dir>

Each reader gets one small request, with the output limit a round would use. The answer says
which provider it went through, or why it could not be reached (no credit, no quota for the
model, a model the provider has retired). `run` and `extend` do this themselves before they start.
"""
import argparse
import json
import sys
from pathlib import Path

from ..config import DEFAULT_FLAGS
from ..page import models_of, reader_entry
from ..preflight import preflight, report


def main(a):
    src = Path(a.source)
    if src.is_dir():
        d = json.loads((src / "page.json").read_text(encoding="utf-8"))
        readers, flags = models_of(d), d["flags"]
    else:
        cfg = json.loads(src.read_text(encoding="utf-8"))
        readers, flags = [reader_entry(m) for m in cfg["models"]], {**DEFAULT_FLAGS, **cfg.get("flags", {})}
    down = report(preflight(readers, flags))
    print(f"{len(readers) - len(down)} of {len(readers)} reader(s) reachable")
    sys.exit(1 if down else 0)


def register(sub):
    p = sub.add_parser("check", help="see that every reader can be reached", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", help="a config file or a run folder")
    p.set_defaults(f=main)
