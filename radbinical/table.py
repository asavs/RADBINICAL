"""Every run flattened into rows, for analysis. Built from runs/*/page.json each time it is read.

    rows()   one dict per comment, runs in folder order, comments in the order they were made
    runs()   one dict per run

`python -m radbinical table` writes both to data/comments.jsonl and data/runs.jsonl.
"""
import json
from pathlib import Path

from .config import ROOT
from .page import is_human


def run_dirs(runs_dir=None):
    """Run folders under runs_dir (default runs/) that hold a page.json, sorted by name."""
    base = Path(runs_dir) if runs_dir else ROOT / "runs"
    return [d for d in sorted(base.iterdir()) if (d / "page.json").exists()] if base.exists() else []


def page_of(d):
    return json.loads((d / "page.json").read_text(encoding="utf-8"))


def comment_rows(run, page):
    """Rows for one page. A reply's start and end are its root's span on the passage. In a fork,
    `inherited` marks the comments copied from the run it was forked from."""
    by_id = {c["id"]: c for c in page["comments"]}
    models = {r["name"]: r["model"] for r in page["readers"]}
    copied = (page.get("forked_from") or {}).get("comments", 0)
    out = []
    for c in sorted(page["comments"], key=lambda c: c["n"]):
        root, depth = c, 0
        while root["target"] != "passage":
            root, depth = by_id[root["target"]], depth + 1
        out.append({
            "run": run, "passage": page["passage"]["id"], "cast": page["cast"], "group": page["group"],
            "lineage": page.get("lineage"), "model": models.get(c["author"]), "reader": c["author"],
            "round": c["layer"], "id": c["id"], "parent": None if c["target"] == "passage" else c["target"],
            "root": root["id"], "depth": depth, "start": root["start"], "end": root["end"],
            "quote": c.get("quote"), "text": c["text"], "see_also": c.get("see_also", []), "kind": c.get("kind"), "stale": c.get("stale"),
            "inherited": c["n"] <= copied,
        })
    return out


def run_cost(d, page):
    """Sum of `cost` over the page's log and the "usage" lists of its side files."""
    usages = [e.get("usage") or {} for e in page["log"]]
    for f in sorted(d.glob("*.json")):
        if f.name != "page.json":
            side = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(side, dict):
                usages += side.get("usage") or []
    return round(sum(u.get("cost", 0) for u in usages if isinstance(u, dict)), 6)


def joined(page):
    """{reader name: the round it joined}. A model reader joins at its first turn in the log, a
    turn with no comments included; a person at the round of their first comment. A reader that
    has done neither is absent."""
    people = {r["name"] for r in page["readers"] if is_human(r)}
    first = {}
    turns = [(e["reader"], e["layer"]) for e in page["log"] if e["reader"] not in people]
    firsts = [(c["author"], c["layer"]) for c in page["comments"] if c["author"] in people and c.get("kind") == "human"]
    for name, layer in turns + firsts:
        first[name] = min(first.get(name, layer), layer)
    return first


def run_row(d, page):
    j = joined(page)
    return {
        "run": d.name, "passage": page["passage"]["id"], "cast": page["cast"], "group": page["group"],
        "lineage": page.get("lineage"),
        "readers": [{"name": r["name"], "model": r["model"], "joined": j.get(r["name"])} for r in page["readers"]],
        "flags": page["flags"], "rounds": page["layers_done"], "comments": len(page["comments"]),
        "cost": run_cost(d, page), "started": page.get("started"),
    }


def rows(runs_dir=None):
    return [r for d in run_dirs(runs_dir) for r in comment_rows(d.name, page_of(d))]


def runs(runs_dir=None):
    return [run_row(d, page_of(d)) for d in run_dirs(runs_dir)]


def write_jsonl(path, items):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")
