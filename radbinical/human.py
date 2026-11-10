"""People as readers.

A person's comments go on the page like any reader's, with `kind: "human"` and the person in
`readers` as {"name", "model": "human:<slug>", "human": true}. Each added comment carries in
`meta` the submission it came from and whether it was written blind.

Where a submission sits:
- blind (written before seeing any model's comment): round 1, comments on the passage only, and
  at most once per person per page. A page with no rounds yet keeps `layers_done` at 0, so the
  models' own first round is round 1 too and, run in parallel, does not see it.
- otherwise: a round of its own after the latest model round, so the next model round sees it.
  People who submit before the models' next round share that round. The page's `layers_done`
  moves up to it.
"""
import copy
import json
import re
from pathlib import Path

from .anchoring import locate
from .page import Page, render_for_reader
from .site import render


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "anon"


def key_of(file):
    """What identifies one submission on a page: its file name."""
    return Path(file).name


def is_human(reader):
    return bool(reader.get("human")) or reader["model"].startswith("human:")


def human_round(d):
    """The round a non-blind submission joins: the latest round if only people wrote in it,
    else the next one."""
    last = d["layers_done"]
    if last:
        authors = {e["reader"] for e in d["log"] if e["layer"] == last} | {c["author"] for c in d["comments"] if c["layer"] == last}
        people = {r["name"] for r in d["readers"] if is_human(r)}
        if authors and authors <= people:
            return last
    return last + 1


def _shape(sub):
    errs = []
    if not isinstance(sub, dict):
        return ["a submission is a JSON object"]
    if not str(sub.get("name") or "").strip():
        errs.append('"name" is missing')
    for k in ("blind", "saw_models"):
        if not isinstance(sub.get(k), bool):
            errs.append(f'"{k}" must be true or false')
    if sub.get("blind") is True and sub.get("saw_models") is True:
        errs.append('"blind" and "saw_models" cannot both be true')
    cs = sub.get("comments")
    if not isinstance(cs, list) or not cs:
        errs.append('"comments" must be a non-empty list')
    elif not all(isinstance(c, dict) for c in cs):
        errs.append("each comment is an object with target, quote and text")
    return errs


def plan(run_dir, sub, file):
    """Check a submission against the page. -> (problems, page with the comments added, new ids).

    The page is a copy; nothing is written. A submission already on the page gives no problems
    and no new ids.
    """
    errs = _shape(sub)
    if errs:
        return errs, None, []
    page = Page.load(run_dir)
    d = copy.deepcopy(page.d)
    work = Page(d, page.dir)
    name, blind, key = sub["name"].strip(), sub["blind"], key_of(file)
    mine = [c for c in d["comments"] if c["author"] == name and c.get("kind") == "human"]
    if any(c.get("meta", {}).get("submission") == key for c in mine):
        return [], work, []
    reader = next((r for r in d["readers"] if r["name"] == name), None)
    if reader and not is_human(reader):
        return [f'"{name}" is already a model reader on this page; choose another name'], None, []
    if blind and mine:
        return [f"{name} already has comments on this page, so a blind submission can no longer be given"], None, []
    if not reader:
        d["readers"].append({"name": name, "model": f"human:{slug(name)}", "human": True})
    layer = 1 if blind else human_round(d)
    meta = {"submission": key, "blind": blind, "saw_models": sub["saw_models"]}
    by_id = {c["id"]: c for c in d["comments"]}
    ids = []
    for i, c in enumerate(sub["comments"], 1):
        target = str(c.get("target", "")).strip().strip("[]")
        where = f"comment {i}"
        if blind and target.lower() != "passage":
            errs.append(f'{where}: a blind submission can only comment on the passage, not "{target}"')
            continue
        if target in by_id and c.get("quote") and not locate(by_id[target]["text"], str(c["quote"])):
            errs.append(f"{where}: the quote was not found in {target}")
            continue
        missing = [r for r in (c.get("see_also") or []) if str(r).strip("[] ") not in by_id]
        if missing:
            errs.append(f"{where}: see_also names no such comment: {', '.join(map(str, missing))}")
            continue
        ok, msg = work.add(name, layer, c, kind="human", meta=meta)
        if ok:
            ids.append(d["comments"][-1]["id"])
        else:
            errs.append(f"{where}: {msg.removeprefix('Not recorded: ')}")
    if errs:
        return errs, None, []
    if not blind:
        d["layers_done"] = max(d["layers_done"], layer)
    d["log"].append({"layer": layer, "reader": name, "model": f"human:{slug(name)}", "via": "human",
                     "comments": len(ids), "usage": {}, "closing": f"From {key}" + (", written blind." if blind else ".")})
    d.pop("at_rest", None)
    return [], work, ids


def problems(run_dir, sub, file):
    return plan(run_dir, sub, file)[0]


def add(run_dir, sub, file):
    """Validate and add a submission. -> (problems, new comment ids). Writes only when both are fine."""
    errs, work, ids = plan(run_dir, sub, file)
    if errs or not ids:
        return errs, []
    work.save()
    render(work.dir)
    return [], ids


def template(run_dir, blind=False):
    """A starter submission and what the person should read before filling it in."""
    d = Page.load(run_dir).d
    p = d["passage"]
    run = Path(run_dir).name
    comments = [{"target": "passage", "quote": "", "text": ""}]
    if not blind:
        comments.append({"target": "c1", "quote": "", "text": "", "see_also": []})
    sub = {"name": "", "blind": blind, "saw_models": not blind, "comments": comments}
    if blind:
        read = "\n".join([p["title"] + (f" ({p['source']})" if p.get("source") else ""), "", p["text"]])
    else:
        read = render_for_reader(d, d["comments"], lambda a: a, None)
    return "\n".join([read, "", f"=== YOUR SUBMISSION: save as humans/{run}/<your-name>.json ===",
                      json.dumps(sub, indent=1, ensure_ascii=False)])
