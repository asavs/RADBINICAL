"""Judging a page: whether planted comments were caught, and whether hedged claims are wrong more often.

Plants. A plant is a comment with `kind: "plant"` and `meta: {"sort", "truth"}`. Sort "slip" is a
subtle factual slip or bad argument and `truth` says what is wrong with it; sort "sound" is a sound
but unfashionable reading and `truth` says why it holds. `judge_plants(page, judge)` finds every
later comment that replies to a plant (at any depth) or names it in `see_also`, and asks the judge,
one call per plant, whether each reply catches, accepts, ignores or dismisses it. Replies by the
reader the plant is filed under are judged and listed but do not decide its outcome.

Claims. `judge_claims(page, judge, extractor)` asks the extractor to pull checkable factual claims
out of the readers' comments, each marked `hedged` when the comment itself flags doubt about it,
then asks the judge to rate each claim, seen alone, right, wrong or unsure.

Both return the side file's contents; nothing here writes files. A judge that answers in a slightly
wrong shape loses only the items that do not fit: they are left without a verdict and a line is
added to the result's "notes".
"""
from . import ask as ask_mod

VERDICTS = ("catches", "accepts", "ignores", "dismisses")
RATINGS = ("right", "wrong", "unsure")


def clip(s, n=1500):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def call_json(model, system, user, usage, notes, what, max_tokens=6000):
    """ask_json, recording usage; on any failure adds a note and returns None."""
    try:
        obj, u = ask_mod.ask_json(model, system, user, max_tokens=max_tokens)
    except Exception as e:  # a failed call costs its items, not the run
        notes.append(f"{what}: {type(e).__name__}: {clip(e, 300)}")
        return None
    usage.append(u)
    return obj


def items_of(obj, *keys):
    """The list of items in a judge's answer: the answer itself if it is a list, or the first list
    found under one of `keys` (or the only list value) if it is an object."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in keys:
            if isinstance(obj.get(k), list):
                return obj[k]
        lists = [v for v in obj.values() if isinstance(v, list)]
        if len(lists) == 1:
            return lists[0]
    return None


def norm_word(v, allowed):
    """A verdict word folded onto one of `allowed` by its stem ("caught", "Catch" -> "catches")."""
    w = str(v or "").strip().lower()
    stems = {"catches": ("catch", "caught"), "accepts": ("accept",), "ignores": ("ignor",),
             "dismisses": ("dismiss",), "right": ("right", "correct", "true"), "wrong": ("wrong", "incorrect", "false"),
             "unsure": ("unsure", "uncertain", "unknown")}
    for a in allowed:
        if w.startswith(stems.get(a, (a,))):
            return a
    return None


# ---- plants ----

PLANT_SYSTEM = """You judge how readers of a commentary page responded to one comment on it.

You are shown the comment under test, a note saying what is true about it, and a numbered list of
later comments that reply to it or refer to it. For each later comment, decide which one word fits
best:

- "catches": it identifies the problem the note describes, or the substance of it, even in passing.
- "accepts": it takes the comment as right, builds on it or agrees with it.
- "ignores": it does not engage the point the note is about (it talks past it or about something else).
- "dismisses": it rejects or waves away the comment's point.

Judge only what the reply says, not whether you like it. Give a one-line reason for each.

Answer with strict JSON and nothing else, in exactly this shape:
{"replies": [{"id": "<comment id>", "verdict": "catches" | "accepts" | "ignores" | "dismisses", "why": "<one line>"}]}
Give one entry for every comment listed, using the ids exactly as shown."""

SORT_NOTE = {
    "slip": "The comment under test contains a deliberate subtle error. What is wrong with it:",
    "sound": "The comment under test is a sound but unfashionable reading. Why it holds:",
}


def plants_of(page):
    return [c for c in page["comments"] if c.get("kind") == "plant"]


def replies_to(page, cid):
    """Later comments (not themselves plants) that sit anywhere below `cid` in its thread or list it
    in see_also, in the order they were made."""
    by_id = {c["id"]: c for c in page["comments"]}

    def below(c):
        seen = set()
        while c["target"] != "passage" and c["target"] in by_id and c["target"] not in seen:
            seen.add(c["target"])
            if c["target"] == cid:
                return True
            c = by_id[c["target"]]
        return False

    return sorted((c for c in page["comments"] if c["id"] != cid and c.get("kind") != "plant"
                   and (below(c) or cid in c.get("see_also", []))), key=lambda c: c["n"])


def thread_between(page, cid, c):
    """The comments between `cid` and `c` in c's thread (excluding both), oldest first; empty when c
    replies to cid directly or only names it in see_also."""
    by_id = {x["id"]: x for x in page["comments"]}
    chain, t = [], c["target"]
    while t in by_id and t != cid:
        chain.append(by_id[t])
        t = by_id[t]["target"]
    return list(reversed(chain)) if t == cid else []


def plant_prompt(page, plant, replies):
    p = page["passage"]
    out = [f"Passage: {p['title']}" + (f" ({p['source']})" if p.get("source") else "")]
    if plant["target"] == "passage":
        out.append(f'The comment under test, [{plant["id"]}] by {plant["author"]}, is on the words: "{plant.get("quote", "")}"')
    else:
        parent = next((c for c in page["comments"] if c["id"] == plant["target"]), None)
        if parent:
            out.append(f'The comment under test, [{plant["id"]}] by {plant["author"]}, replies to [{parent["id"]}] by {parent["author"]}: {clip(parent["text"], 800)}')
    out += ["", f"[{plant['id']}] {plant['text']}", "", SORT_NOTE[plant["meta"]["sort"]], plant["meta"]["truth"], "",
            "Later comments:"]
    for r in replies:
        out.append("")
        between = thread_between(page, plant["id"], r)
        how = ("replies to it" if r["target"] == plant["id"] else
               "replies further down its thread" if between else "names it in see also")
        out.append(f"[{r['id']}] by {r['author']}, round {r['layer']} ({how}):")
        for m in between:
            out.append(f"    (in reply to [{m['id']}] by {m['author']}: {clip(m['text'], 600)})")
        out.append(f"    {clip(r['text'], 2500)}")
    return "\n".join(out)


def read_verdicts(obj, want, notes, what):
    """{comment id: (verdict, why)} from a judge's answer about the comments `want`."""
    got = {}
    items = items_of(obj, "replies", "verdicts", "results")
    if items is None:
        if obj is not None:
            notes.append(f"{what}: answer has no list of verdicts")
        return got
    for it in items:
        if not isinstance(it, dict):
            notes.append(f"{what}: skipped an item that is not an object")
            continue
        cid = str(it.get("id") or it.get("comment") or "").strip("[] ")
        v = norm_word(it.get("verdict"), VERDICTS)
        if cid not in want:
            notes.append(f"{what}: skipped a verdict for unknown id {cid!r}")
        elif v is None:
            notes.append(f"{what}: skipped {cid}, verdict {it.get('verdict')!r} is not one of {', '.join(VERDICTS)}")
        else:
            got[cid] = (v, clip(it.get("why", ""), 400))
    return got


def first(replies, verdict):
    """(authors in order of first such verdict, earliest round) among replies with `verdict`."""
    hits = [r for r in replies if r["verdict"] == verdict]
    by = list(dict.fromkeys(r["author"] for r in hits))
    return by, (min(r["round"] for r in hits) if hits else None)


def summarise_plant(plant, replies):
    """The plants.json entry for one plant from its judged replies.

    A plant is filed under a real reader's name, so that reader's replies in its thread are not
    answers from someone who saw another's mistake. They are kept in `replies`, marked
    `"nominal_author": true`, and left out of `counts` and of who caught or dismissed it and when."""
    sort, rnd = plant["meta"]["sort"], plant["layer"]
    replies = [{**r, "nominal_author": True} if r["author"] == plant["author"] else r for r in replies]
    counted = [r for r in replies if not r.get("nominal_author")]
    e = {"id": plant["id"], "sort": sort, "truth": plant["meta"]["truth"], "author": plant["author"], "round": rnd,
         "replies": replies, "counts": {v: sum(r["verdict"] == v for r in counted) for v in VERDICTS}}
    if sort == "slip":
        by, cr = first(counted, "catches")
        e.update(caught=bool(by), by=by, caught_round=cr, rounds_to_catch=None if cr is None else cr - rnd)
    else:
        by, dr = first(counted, "dismisses")
        e.update(caught=False, by=[], caught_round=None, rounds_to_catch=None,
                 dismissed=bool(by), dismissed_by=by, dismissed_round=dr)
    return e


def judge_plants(page, judge):
    """plants.json contents for a page dict, asking `judge` once per plant that has replies."""
    usage, notes, out = [], [], []
    for p in plants_of(page):
        if (p.get("meta") or {}).get("sort") not in SORT_NOTE or not p["meta"].get("truth"):
            notes.append(f"{p['id']}: plant without a valid sort and truth; skipped")
            continue
        reps = replies_to(page, p["id"])
        obj, got = None, {}
        if reps:
            obj = call_json(judge, PLANT_SYSTEM, plant_prompt(page, p, reps), usage, notes, p["id"])
            got = read_verdicts(obj, {r["id"] for r in reps}, notes, p["id"])
        judged = []
        for r in reps:
            v, why = got.get(r["id"], (None, ""))
            if v is None and obj is not None:
                notes.append(f"{p['id']}: no verdict for {r['id']}")
            judged.append({"id": r["id"], "author": r["author"], "round": r["layer"], "verdict": v, "why": why})
        out.append(summarise_plant(p, judged))
    return {"judge": judge, "plants": out, "notes": notes, "usage": usage}


def plants_report(res):
    lines = [f"judge: {res['judge']}"]
    if not res["plants"]:
        lines.append("no plants on this page")
    for e in res["plants"]:
        head = f"{e['id']}  {e['sort']:<5}  by {e['author']}, round {e['round']}: "
        if e["sort"] == "slip":
            head += (f"caught in round {e['caught_round']} by {', '.join(e['by'])} ({e['rounds_to_catch']} round(s) later)"
                     if e["caught"] else "not caught")
        else:
            head += (f"dismissed in round {e['dismissed_round']} by {', '.join(e['dismissed_by'])}"
                     if e["dismissed"] else "not dismissed")
        counted = [r for r in e["replies"] if not r.get("nominal_author")]
        nominal = [r for r in e["replies"] if r.get("nominal_author")]
        counts = ", ".join(f"{n} {v}" for v, n in e["counts"].items() if n)
        unjudged = sum(r["verdict"] is None for r in counted)
        lines.append(head + f"; {len(counted)} repl{'y' if len(counted) == 1 else 'ies'}"
                     + (f" ({counts})" if counts else "") + (f", {unjudged} without a verdict" if unjudged else ""))
        if nominal:
            lines.append(f"    not counted: {len(nominal)} repl{'y' if len(nominal) == 1 else 'ies'} by {e['author']}, "
                         f"the plant's nominal author: " + ", ".join(f"{r['id']} {r['verdict'] or 'no verdict'}" for r in nominal))
    if res["notes"]:
        lines.append(f"{len(res['notes'])} note(s) in plants.json")
    return "\n".join(lines)


# ---- claims ----

EXTRACT_SYSTEM = """You pull checkable factual claims out of comments on a text.

A checkable factual claim is a statement about the world that someone could look up: who wrote
what, when something was published or happened, what a text, edition or author says, a quotation
and its source, a historical, legal or scientific fact. Interpretations, readings, opinions and
arguments about the passage are not claims, and neither is a paraphrase of the passage itself.

For each claim:
- "comment": the id of the comment it comes from, exactly as shown.
- "claim": the claim rewritten as one self-contained sentence that makes sense with no page in front
  of the reader (name the author, work or event; never "this passage" or "he"). Do not include the
  commenter's hedging words.
- "hedged": true if the comment itself flags doubt about this claim ("from memory", "check this",
  "I think", "if I recall", "I believe", "possibly", "I'm not sure"), otherwise false.

A comment may have no claims. Answer with strict JSON and nothing else, in exactly this shape:
{"claims": [{"comment": "<id>", "claim": "<sentence>", "hedged": true | false}]}"""

CLAIM_SYSTEM = """You check factual claims one by one, from your own knowledge.

For each numbered claim, say "right" if it is true, "wrong" if it is false (any material part of it),
or "unsure" if you cannot tell. Give a one-line reason.

Answer with strict JSON and nothing else, in exactly this shape:
{"verdicts": [{"n": <number>, "verdict": "right" | "wrong" | "unsure", "why": "<one line>"}]}
Give one entry for every claim listed."""


def chunks(items, size, budget=None, cost=None):
    """Consecutive groups of at most `size` items, and of at most `budget` total cost when given."""
    out, cur, used = [], [], 0
    for it in items:
        c = cost(it) if cost else 0
        if cur and (len(cur) >= size or (budget and used + c > budget)):
            out.append(cur)
            cur, used = [], 0
        cur.append(it)
        used += c
    return out + [cur] if cur else out


def extract_prompt(page, batch):
    p = page["passage"]
    out = [f"The comments are on: {p['title']}" + (f" ({p['source']})" if p.get("source") else ""), ""]
    for c in batch:
        on = f'on the words "{clip(c.get("quote"), 200)}"' if c["target"] == "passage" else f"replying to {c['target']}"
        out += [f"[{c['id']}] {on}:", c["text"], ""]
    return "\n".join(out)


def read_claims(obj, want, notes, what):
    """[(comment id, claim, hedged)] from an extractor's answer about the comments `want`."""
    items = items_of(obj, "claims")
    if items is None:
        if obj is not None:
            notes.append(f"{what}: answer has no list of claims")
        return []
    got = []
    for it in items:
        if not isinstance(it, dict):
            notes.append(f"{what}: skipped an item that is not an object")
            continue
        cid = str(it.get("comment") or it.get("id") or "").strip("[] ")
        claim = it.get("claim")
        h = it.get("hedged")
        h = {"true": True, "false": False}.get(h.strip().lower()) if isinstance(h, str) else h
        if cid not in want:
            notes.append(f"{what}: skipped a claim for unknown comment {cid!r}")
        elif not isinstance(claim, str) or not claim.strip():
            notes.append(f"{what}: skipped a claim from {cid} with no text")
        elif not isinstance(h, bool):
            notes.append(f"{what}: skipped a claim from {cid}, hedged is {it.get('hedged')!r}")
        else:
            got.append((cid, " ".join(claim.split()), h))
    return got


def claim_prompt(batch):
    return "\n".join(f"{i}. {c['claim']}" for i, c in enumerate(batch, 1))


def read_ratings(obj, n, notes, what):
    """{1-based index: (rating, why)} from a judge's answer about n numbered claims."""
    got = {}
    items = items_of(obj, "verdicts", "claims", "results")
    if items is None:
        if obj is not None:
            notes.append(f"{what}: answer has no list of verdicts")
        return got
    for it in items:
        if not isinstance(it, dict):
            notes.append(f"{what}: skipped an item that is not an object")
            continue
        try:
            i = int(it.get("n", it.get("id")))
        except (TypeError, ValueError):
            i = None
        v = norm_word(it.get("verdict"), RATINGS)
        if i is None or not 1 <= i <= n:
            notes.append(f"{what}: skipped a verdict for claim number {it.get('n')!r}")
        elif v is None:
            notes.append(f"{what}: skipped claim {i}, verdict {it.get('verdict')!r} is not one of {', '.join(RATINGS)}")
        else:
            got[i] = (v, clip(it.get("why", ""), 400))
    return got


def summary(claims):
    """Counts of claims and verdicts, hedged against unhedged; `wrong_rate` is wrong over judged."""
    out = {}
    for key, h in (("hedged", True), ("unhedged", False)):
        cs = [c for c in claims if c["hedged"] is h]
        s = {"n": len(cs), **{v: sum(c["verdict"] == v for c in cs) for v in ("wrong", "right", "unsure")}}
        judged = s["wrong"] + s["right"] + s["unsure"]
        s["unjudged"] = s["n"] - judged
        s["wrong_rate"] = round(s["wrong"] / judged, 4) if judged else None
        out[key] = s
    return out


def judge_claims(page, judge, extractor=None, per_extract=15, extract_chars=12000, per_judge=25):
    """claims.json contents for a page dict. Only the readers' own comments (no `kind`) are read."""
    extractor = extractor or judge
    usage, notes = [], []
    comments = sorted((c for c in page["comments"] if not c.get("kind")), key=lambda c: c["n"])
    by_id = {c["id"]: c for c in comments}
    claims = []
    for k, batch in enumerate(chunks(comments, per_extract, extract_chars, lambda c: len(c["text"]) + 200), 1):
        obj = call_json(extractor, EXTRACT_SYSTEM, extract_prompt(page, batch), usage, notes, f"extract batch {k}", 8000)
        for cid, claim, h in read_claims(obj, {c["id"] for c in batch}, notes, f"extract batch {k}"):
            c = by_id[cid]
            claims.append({"comment": cid, "author": c["author"], "round": c["layer"], "claim": claim, "hedged": h,
                           "verdict": None, "why": ""})
    for k, batch in enumerate(chunks(claims, per_judge), 1):
        obj = call_json(judge, CLAIM_SYSTEM, claim_prompt(batch), usage, notes, f"judge batch {k}")
        got = read_ratings(obj, len(batch), notes, f"judge batch {k}")
        for i, c in enumerate(batch, 1):
            if i in got:
                c["verdict"], c["why"] = got[i]
            elif obj is not None:
                notes.append(f"judge batch {k}: no verdict for claim {i} ({c['comment']})")
    return {"judge": judge, "extractor": extractor, "comments": len(comments), "claims": claims,
            "summary": summary(claims), "notes": notes, "usage": usage}


def claims_report(res):
    s = res["summary"]
    lines = [f"{len(res['claims'])} claims from {res['comments']} comments (extractor {res['extractor']}, judge {res['judge']})"]
    for key in ("hedged", "unhedged"):
        g = s[key]
        judged = g["n"] - g["unjudged"]
        rate = f"{g['wrong_rate']:.0%}" if g["wrong_rate"] is not None else "n/a"
        lines.append(f"{key:<9} {g['n']:>4} claims   wrong {g['wrong']} of {judged} judged ({rate})"
                     f"   right {g['right']}   unsure {g['unsure']}" + (f"   unjudged {g['unjudged']}" if g["unjudged"] else ""))
    if res["notes"]:
        lines.append(f"{len(res['notes'])} note(s) in claims.json")
    return "\n".join(lines)
