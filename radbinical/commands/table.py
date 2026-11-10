"""Flatten every run into data/comments.jsonl (one row per comment) and data/runs.jsonl (one per run).

    python -m radbinical table
    python -m radbinical table --runs some/runs --out some/data
"""
import argparse
from pathlib import Path

from ..config import ROOT
from ..table import rows, runs, write_jsonl


def main(a):
    out = Path(a.out) if a.out else ROOT / "data"
    c, r = rows(a.runs), runs(a.runs)
    write_jsonl(out / "comments.jsonl", c)
    write_jsonl(out / "runs.jsonl", r)
    print(f"{len(c)} comments, {len(r)} runs -> {out}")


def register(sub):
    p = sub.add_parser("table", help="flatten every run into data/*.jsonl", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", help="folder of runs (default runs/)")
    p.add_argument("--out", help="folder to write into (default data/)")
    p.set_defaults(f=main)
