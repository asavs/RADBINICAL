"""Every run flattened into rows, for analysis. Built from runs/*/page.json each time it is read.

    rows()   one dict per comment, runs in folder order, comments in the order they were made
    runs()   one dict per run

`python -m radbinical table` writes both to data/comments.jsonl and data/runs.jsonl.
"""
import json
from pathlib import Path

from .config import ROOT
from .page import is_human, thread
from .prices import complete, costs


def run_dirs(runs_dir=None):
    """Run folders under runs_dir (default runs/) that hold a page.json, sorted by name."""
    base = Path(runs_dir) if runs_dir else ROOT / "runs"
    return [d for d in sorted(base.iterdir()) if (d / "page.json").exists()] if base.exists() else []


def page_of(d):
    return json.loads((d / "page.json").read_text(encoding="utf-8"))


def comment_rows(run, page):
    """Rows for one page. A reply's start and end are its root's span on the passage. `repeat_of`
    is the id of the first earlier comment by the same reader with the same words (spacing aside),
    wherever on the page either was put."""
    models = {r["name"]: r["model"] for r in page["readers"]}
    out, said = [], {}
    for c in sorted(page["comments"], key=lambda c: c["n"]):
        first = said.setdefault((c["author"], " ".join(c["text"].split())), c["id"])
        chain = thread(page, c)
        root, depth = chain[0], len(chain) - 1
        out.append({
            "run": run, "passage": page["passage"]["id"], "cast": page["cast"], "group": page["group"],
            "model": models.get(c["author"]), "reader": c["author"],
            "round": c["layer"], "id": c["id"], "parent": None if c["target"] == "passage" else c["target"],
            "root": root["id"], "depth": depth, "start": root["start"], "end": root["end"],
            "quote": c.get("quote"), "text": c["text"], "see_also": c.get("see_also", []), "kind": c.get("kind"),
            "repeat_of": None if first == c["id"] else first,
        })
    return out


def usages(page):
    """Every usage dict in a run's log, each priced as in radbinical/prices.py when it has tokens
    but no cost."""
    return [complete(e.get("model", ""), dict(e.get("usage") or {})) for e in page["log"]]


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
    """One run's row. `cost` is every call's cost, reported or estimated; `cost_estimated` is the
    part of it estimated from tokens."""
    reported, estimated = costs(usages(page))
    j = joined(page)
    return {
        "run": d.name, "passage": page["passage"]["id"], "cast": page["cast"], "group": page["group"],
        "readers": [{"name": r["name"], "model": r["model"], "joined": j.get(r["name"])} for r in page["readers"]],
        "flags": page["flags"], "rounds": page["layers_done"], "comments": len(page["comments"]),
        "cost": round(reported + estimated, 6), "cost_estimated": estimated, "started": page.get("started"),
    }


def rows(runs_dir=None):
    return [r for d in run_dirs(runs_dir) for r in comment_rows(d.name, page_of(d))]


def runs(runs_dir=None):
    return [run_row(d, page_of(d)) for d in run_dirs(runs_dir)]


def write_jsonl(path, items):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")
