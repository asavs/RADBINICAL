"""Cluster glosses into readings across runs, and measure how often readings recur.

    python -m radbinical readings
    python -m radbinical readings --embed mock:bow --runs some/runs --out some/data

Writes <out>/readings.jsonl (one row per reading), <out>/reading_members.jsonl (one row per
gloss, naming its reading) and <out>/noise.jsonl (the noise floor). Embeddings are cached in
<out>/embeddings/. The clustering method is described in radbinical/readings.py.

Noise floor: for each group of two or more runs of one config, the share of readings found in
every run, in two or more, and in only one, over all rounds and over round 1 alone (the blind
round, where no reader has seen another's comments), and the mean Jaccard overlap between the
runs' sets of readings. The same between casts on one passage is printed for comparison.
"""
import argparse
import sys
from pathlib import Path

from ..config import ROOT
from ..embed import DEFAULT
from ..readings import MIN_OVERLAP, default_threshold, noise, readings
from ..table import rows, runs, write_jsonl


def add_options(p):
    p.add_argument("--runs", help="folder of runs (default runs/)")
    p.add_argument("--out", help="folder to write into (default data/)")
    p.add_argument("--embed", default=DEFAULT, help=f"embedding model (default {DEFAULT})")
    p.add_argument("--threshold", type=float, help="cosine needed to merge clusters (default per model: 0.3 for mock:, 0.84 for google:, 0.8 otherwise)")
    p.add_argument("--min-overlap", type=float, default=MIN_OVERLAP,
                   help=f"span overlap, over the shorter span, below which two glosses never count as similar (default {MIN_OVERLAP})")


def build(a):
    """(out dir, rows, readings, members) for parsed options."""
    out = Path(a.out) if a.out else ROOT / "data"
    rs = rows(a.runs)
    rd, ms = readings(rs, a.embed, a.threshold, a.min_overlap, out / "embeddings")
    return out, rs, rd, ms


def safe(text):
    """text with any character the terminal's encoding cannot show replaced by '?'."""
    enc = sys.stdout.encoding or "utf-8"
    return text.encode(enc, "replace").decode(enc)


def clip(text, n):
    """The first n characters of text on one line, quoted, safe to print."""
    return safe(repr(" ".join(text.split())[:n]))


def fmt(x):
    return "-" if x is None else f"{x:.2f}"


def print_noise(rows_):
    print("\nNoise floor. A reading counts as present in a run (or cast) if any gloss of that run is a member.")
    print("Shares are over readings present in at least one unit; 'in 2+' includes 'in all'.")
    groups = [r for r in rows_ if r["scope"] == "group"]
    if not groups:
        print("  No group has two or more runs, so nothing here separates a reading from noise.")
    for r in rows_:
        label = f"group {r['key']}" if r["scope"] == "group" else f"casts on {r['passage']} (comparison)"
        print(f"  {label}: {len(r['units'])} units")
        for name in ("all_rounds", "round1"):
            m = r[name]
            print(f"    {name:10} readings {m['readings']:3}  in all {fmt(m['share_all'])}  in 2+ {fmt(m['share_2plus'])}"
                  f"  in 1 {fmt(m['share_1'])}  mean Jaccard {fmt(m['jaccard'])}")
    print("  Recurrence depends on the threshold: a lower one merges more and makes everything recur.")


def main(a):
    out, rs, rd, ms = build(a)
    nz = noise(ms, runs(a.runs))
    write_jsonl(out / "readings.jsonl", rd)
    write_jsonl(out / "reading_members.jsonl", ms)
    write_jsonl(out / "noise.jsonl", nz)
    t = default_threshold(a.embed) if a.threshold is None else a.threshold
    print(f"{len(ms)} glosses -> {len(rd)} readings  (embed {a.embed}, threshold {t}, min overlap {a.min_overlap})")
    for r in sorted(rd, key=lambda r: (-r["size"], r["id"]))[:12]:
        if r["size"] < 2:
            break
        rep = r["representative"]
        print(f"  {r['id']:24} size {r['size']:2}  runs {len(r['runs'])}  models {len(r['models'])}  "
              f"replies {r['replies']:2}  {rep['run']}/{rep['id']}: {clip(rep['text'], 70)}")
    print_noise(nz)
    print(f"-> {out}")


def register(sub):
    p = sub.add_parser("readings", help="cluster glosses into readings; noise floor", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    add_options(p)
    p.set_defaults(f=main)
