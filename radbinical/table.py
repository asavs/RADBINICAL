"""Every run flattened into rows, for analysis. Built from runs/*/page.json each time it is read.

    rows()   one dict per comment, runs in folder order, comments in the order they were made
    runs()   one dict per run

`python -m radbinical table` writes both to data/comments.jsonl and data/runs.jsonl.
"""
import json
from pathlib import Path

from .config import ROOT


def run_dirs(runs_dir=None):
    """Run folders under runs_dir (default runs/) that hold a page.json, sorted by name."""
    base = Path(runs_dir) if runs_dir else ROOT / "runs"
    return [d for d in sorted(base.iterdir()) if (d / "page.json").exists()] if base.exists() else []


def _page(d):
    return json.loads((d / "page.json").read_text(encoding="utf-8"))


def comment_rows(run, page):
    """Rows for one page. A reply's start and end are its root's span on the passage."""
    by_id = {c["id"]: c for c in page["comments"]}
    models = {r["name"]: r["model"] for r in page["readers"]}
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


def run_row(d, page):
    return {
        "run": d.name, "passage": page["passage"]["id"], "cast": page["cast"], "group": page["group"],
        "lineage": page.get("lineage"), "readers": [{"name": r["name"], "model": r["model"]} for r in page["readers"]],
        "flags": page["flags"], "rounds": page["layers_done"], "comments": len(page["comments"]),
        "cost": run_cost(d, page), "started": page.get("started"),
    }


def rows(runs_dir=None):
    return [r for d in run_dirs(runs_dir) for r in comment_rows(d.name, _page(d))]


def runs(runs_dir=None):
    return [run_row(d, _page(d)) for d in run_dirs(runs_dir)]


def write_jsonl(path, items):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")
