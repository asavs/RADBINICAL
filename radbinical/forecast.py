"""Forecasts: before a round, each reader names the comments it expects to draw replies.

With the `forecast` flag on, `run_layers` makes a `Forecaster` for every round after the first.
Just before a reader's annotating turn, `Forecaster.ask` renders the page exactly as that turn
will see it and sends a separate one-shot `ask` call for JSON in the background; the turn itself is
untouched. After the round, `Forecaster.finish` collects the answers, scores them against the
replies the round produced, and appends them to the side file `forecasts.json`:

    {"forecasts": [{"round", "reader", "model", "predicted": [ids], "probabilities": {id: p},
                    "seen": [ids on the page the reader saw], "replied": [ids], "hits": [ids],
                    "by_forecaster": [ids], "precision", "recall", "chance"}],
     "usage": [...]}

`replied` is the seen comments that drew, during the round and after the reader looked, a reply
from someone other than the comment's own author. `by_forecaster` is the part of `replied` the
forecaster itself replied to (a forecast can make itself come true). `chance` is the precision a
forecaster naming the same number of seen comments at random would expect: the share of seen
comments that drew a reply. A failed forecast carries "error" and no scores.
"""
import concurrent.futures as cf

from . import ask as ask_mod
from .page import render_for_reader


SYSTEM = (
    "You are one of several readers annotating a passage together over rounds; comments in the "
    "margins can reply to one another. This is a separate question asked before your turn, and "
    "your answer is not shown to anyone on the page. Look at the margins as they stand and say "
    "which existing comments you expect to draw at least one reply, from a reader other than the "
    "comment's author, during this round. Name as many or as few as you expect.\n\n"
    "Answer with JSON only: one object, no other text."
)

ASK = ('\n\n=== THE QUESTION ===\nWhich of the comments above will draw at least one reply from '
       'another reader this round? Answer as {"expect": ["c3", "c7"], "probabilities": {"c3": 0.8, '
       '"c7": 0.6}}. "probabilities" is optional: your chance, 0 to 1, for each id you name.')


def parse(obj, known):
    """(predicted ids, probabilities, ids not on the page) from a model's answer.

    Accepts {"expect": [...]} (or "ids"/"comments"), a bare list, and list items that are ids or
    {"id": ..., "p": ...}. Raises ValueError when no list of ids can be found.
    """
    probs = {}
    if isinstance(obj, dict):
        raw = next((obj[k] for k in ("expect", "ids", "comments", "predicted") if isinstance(obj.get(k), list)), None)
        if isinstance(obj.get("probabilities"), dict):
            probs = obj["probabilities"]
    else:
        raw = obj
    if not isinstance(raw, list):
        raise ValueError(f"expected a list of comment ids, got {str(obj)[:200]!r}")
    ids = []
    for x in raw:
        if isinstance(x, dict):
            cid = x.get("id")
            if "p" in x or "probability" in x:
                probs = {**probs, str(cid).strip("[] "): x.get("p", x.get("probability"))}
        else:
            cid = x
        cid = str(cid).strip("[] ")
        if cid and cid not in ids:
            ids.append(cid)
    good = [i for i in ids if i in known]
    p = {}
    for k, v in probs.items():
        k = str(k).strip("[] ")
        if k in good and isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1:
            p[k] = float(v)
    return good, p, [i for i in ids if i not in known]


def replied_ids(comments, layer, seen):
    """{id of a seen comment: authors who replied to it} for replies made in `layer` that the
    forecaster had not seen, by someone other than the comment's author."""
    by_id = {c["id"]: c for c in comments}
    out = {}
    for c in comments:
        t = c.get("target")
        if c["layer"] == layer and c["id"] not in seen and t in seen and t in by_id and c["author"] != by_id[t]["author"]:
            out.setdefault(t, set()).add(c["author"])
    return out


def score(f, comments):
    """Fill in replied, hits, by_forecaster, precision, recall and chance on forecast `f`."""
    seen = f["seen"]
    got = replied_ids(comments, f["round"], set(seen))
    replied = [i for i in seen if i in got]
    hits = [i for i in f["predicted"] if i in got]
    f["replied"], f["hits"] = replied, hits
    f["by_forecaster"] = [i for i in replied if f["reader"] in got[i]]
    f["precision"] = round(len(hits) / len(f["predicted"]), 4) if f["predicted"] else None
    f["recall"] = round(len(hits) / len(replied), 4) if replied else None
    f["chance"] = round(len(replied) / len(seen), 4) if seen else None
    return f


class Forecaster:
    """The forecasts of one round. `ask` before each turn, `finish` once the round is done."""

    def __init__(self, page, layer, label, workers=8):
        self.page, self.layer, self.label = page, layer, label
        self.pool = cf.ThreadPoolExecutor(max(1, min(workers, len(page.d["readers"]))))
        self.jobs = []

    def ask(self, reader, visible, note=""):
        """Render the page as `reader` sees it now and send its forecast in the background."""
        me = reader["name"]
        user = f"Round {self.layer}. {note}\n\n" + render_for_reader(self.page.d, visible, self.label, me) + ASK
        entry = {"round": self.layer, "reader": me, "model": reader["model"], "seen": [c["id"] for c in visible]}
        self.jobs.append((entry, self.pool.submit(ask_mod.ask, reader["model"], SYSTEM, user, 2000)))

    def finish(self):
        """Wait for the answers, score them, append them to forecasts.json; returns the entries."""
        done, usage = [], []
        for entry, job in self.jobs:
            try:
                text, u = job.result()
                usage.append(u)
                obj = ask_mod.extract_json(text, entry["model"])
                entry["predicted"], probs, unknown = parse(obj, set(entry["seen"]))
                if probs:
                    entry["probabilities"] = probs
                if unknown:
                    entry["unknown"] = unknown
                score(entry, self.page.d["comments"])
            except Exception as e:  # one reader's failed forecast should not sink the round
                entry["error"] = f"{type(e).__name__}: {e}"[:600]
            done.append(entry)
        self.pool.shutdown()
        side = self.page.side("forecasts") or {"forecasts": [], "usage": []}
        side["forecasts"] += done
        side["usage"] = (side.get("usage") or []) + usage
        self.page.save_side("forecasts", side)
        return done


def rescore(page):
    """Recompute the scores in forecasts.json from page.json. Returns the side file."""
    side = page.side("forecasts") or {"forecasts": [], "usage": []}
    for f in side["forecasts"]:
        if "error" not in f:
            score(f, page.d["comments"])
    page.save_side("forecasts", side)
    return side


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def summary(forecasts, key):
    """{key value: totals} over forecasts grouped by `key` ("reader" or "round"): counts, mean
    precision, recall and chance, and pooled precision (all hits over all names)."""
    out = {}
    for f in forecasts:
        g = out.setdefault(f[key], {"forecasts": 0, "errors": 0, "named": 0, "hits": 0, "replied": 0,
                                    "self": 0, "_p": [], "_r": [], "_c": []})
        g["forecasts"] += 1
        if "error" in f:
            g["errors"] += 1
            continue
        g["named"] += len(f["predicted"])
        g["hits"] += len(f["hits"])
        g["replied"] += len(f["replied"])
        g["self"] += len(set(f["hits"]) & set(f.get("by_forecaster", [])))
        g["_p"].append(f["precision"]); g["_r"].append(f["recall"]); g["_c"].append(f["chance"])
    for g in out.values():
        g["precision"], g["recall"], g["chance"] = _mean(g.pop("_p")), _mean(g.pop("_r")), _mean(g.pop("_c"))
        g["pooled_precision"] = round(g["hits"] / g["named"], 4) if g["named"] else None
    return out
