"""The reply graph: who builds on which comment.

    python -m radbinical graph
    python -m radbinical graph --runs some/runs --out some/data

Nodes are comments. Edges run from a reply to its parent ("reply") and from a comment to each
comment in its see_also ("see_also"). Writes <out>/graph.jsonl, one row per comment:

    replies_in      direct replies to it
    see_also_in     comments citing it in see_also
    descendants     all replies below it
    subtree_readers distinct readers among those replies
    builds_on       distinct comments by other readers that reply below it or cite it

and <out>/graph_runs.jsonl, one row per run: share of comments with no replies, deepest reply,
the who-replies-to-whom matrix, and reciprocity (of reader pairs with a reply between them in
either direction, the share with replies both ways). Prints the comments most built on per run.
"""
import argparse
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from ..config import ROOT
from ..readings import descendants, threads
from ..table import rows, write_jsonl
from .readings import clip, safe


def nodes(rs):
    children, cited = threads(rs)
    out = []
    for r in rs:
        key = (r["run"], r["id"])
        below = descendants(key, children)
        builders = {(c["run"], c["id"]) for c in below + cited.get(key, []) if c["reader"] != r["reader"]}
        out.append({
            "run": r["run"], "id": r["id"], "reader": r["reader"], "model": r["model"], "round": r["round"],
            "depth": r["depth"], "parent": r["parent"], "see_also": r["see_also"],
            "replies_in": len(children.get(key, [])), "see_also_in": len(cited.get(key, [])),
            "descendants": len(below), "subtree_readers": len({c["reader"] for c in below}),
            "builds_on": len(builders),
        })
    return out


def run_summaries(rs, ns):
    by_id = {(r["run"], r["id"]): r for r in rs}
    out = []
    for run in dict.fromkeys(r["run"] for r in rs):
        mine = [n for n in ns if n["run"] == run]
        matrix = defaultdict(lambda: defaultdict(int))
        for r in rs:
            if r["run"] == run and r["parent"]:
                matrix[r["reader"]][by_id[(run, r["parent"])]["reader"]] += 1
        readers = sorted({n["reader"] for n in mine})
        linked = mutual = 0
        for a, b in combinations(readers, 2):
            ab, ba = matrix.get(a, {}).get(b, 0), matrix.get(b, {}).get(a, 0)
            linked += bool(ab or ba)
            mutual += bool(ab and ba)
        out.append({
            "run": run, "comments": len(mine),
            "share_no_replies": round(sum(n["replies_in"] == 0 for n in mine) / len(mine), 4),
            "max_depth": max(n["depth"] for n in mine),
            "replies": {a: dict(b) for a, b in sorted(matrix.items())},
            "reader_pairs_linked": linked, "reader_pairs_mutual": mutual,
            "reciprocity": round(mutual / linked, 4) if linked else None,
        })
    return out


def main(a, top=5):
    out = Path(a.out) if a.out else ROOT / "data"
    rs = rows(a.runs)
    ns = nodes(rs)
    rn = run_summaries(rs, ns)
    write_jsonl(out / "graph.jsonl", ns)
    write_jsonl(out / "graph_runs.jsonl", rn)
    text = {(r["run"], r["id"]): r["text"] for r in rs}
    for s in rn:
        recip = "-" if s["reciprocity"] is None else f"{s['reciprocity']:.2f}"
        print(f"{s['run']}: {s['comments']} comments, {s['share_no_replies']:.0%} with no replies, max depth "
              f"{s['max_depth']}, reciprocity {recip} ({s['reader_pairs_mutual']}/{s['reader_pairs_linked']} reader pairs)")
        ranked = sorted((n for n in ns if n["run"] == s["run"] and n["builds_on"]),
                        key=lambda n: (-n["builds_on"], -n["descendants"], n["round"]))
        for n in ranked[:top]:
            print(f"  {n['id']:5} r{n['round']} {safe(n['reader'][:18]):18} builds_on {n['builds_on']:2}  desc {n['descendants']:2}"
                  f"  cited {n['see_also_in']:2}  readers {n['subtree_readers']}  {clip(text[(n['run'], n['id'])], 60)}")
    print(f"-> {out}")


def register(sub):
    p = sub.add_parser("graph", help="reply and see_also graph; most built-on comments", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", help="folder of runs (default runs/)")
    p.add_argument("--out", help="folder to write into (default data/)")
    p.set_defaults(f=main)
