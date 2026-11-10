"""The redactor: models compile a page into what is disputed, settled and unresolved.

A redactor reads the whole page and reports the state of the discussion without ruling on it.
Each item it returns is

    {"status": "disputed" | "settled" | "unresolved", "summary": "...",
     "cites": ["c3", "c7"], "quotes": [{"id": "c3", "text": "exact words from c3"}]}

and carries a `check`: mechanical checks that need no model (`ids_ok`, `missing`, `quotes_ok`,
`unfound`), and, once `judge_items` has run, a judge's `verdict` ("supported", "distorted" or
"unsupported") and `why`.

Everything lives in the run's side file `redactions.json`:

    {"redactions": [{"model", "name", "signed", "items": [...], "notes"?: [...], "error"?: "..."}],
     "compare": {...}, "usage": [...]}

`compare` is recomputed whenever the redactions change. A comment's `kind` and `meta` are never
shown to the redactor or the judge.
"""
import concurrent.futures as cf
import itertools
import re

from . import ask as ask_mod
from .anchoring import locate
from .page import labeller, reader_entry, render_for_reader

STATUSES = ("disputed", "settled", "unresolved")
VERDICTS = ("supported", "distorted", "unsupported")
SIDE = "redactions"

SYSTEM = """You are the redactor of a page of marginal commentary. Several readers have annotated \
a passage and replied to one another over rounds. Your job is to report the state of the \
discussion as it stands on the page. You do not rule on who is right, you add no arguments of \
your own, and you do not assess the passage. You compile; you decide nothing.

Report each line of discussion as one item, with one of three statuses:
- "disputed": the readers disagree and the disagreement is still live, with positions on each side.
- "settled": the readers themselves reached agreement, or a claim was withdrawn or conceded by \
its author. Settled means settled by the readers, never by you.
- "unresolved": a question was raised and left open; nobody answered it, or the answers do not close it.

For each item give:
- "status": one of the three above.
- "summary": one or two sentences saying what the item is about and where it stands on the page, \
attributing each position to the reader who holds it, by the name shown on the page.
- "cites": the ids of every comment the item rests on, e.g. ["c3", "c7"].
- "quotes": a few short quotations showing the positions, each {"id": a comment id, "text": words \
copied exactly from that comment}.

Cite only ids shown on the page. Quote only words that appear in the comment you name.
Answer with JSON only: {"items": [ ... ]}."""

JUDGE_SYSTEM = """You check one item of a redactor's report on a discussion against the comments \
it cites. The redactor was asked to report the state of the discussion (disputed, settled or \
unresolved) without ruling on it. You are not asked whether the readers are right, only whether \
the item reports them faithfully.

Rate the item:
- "supported": the summary and its status match what the cited comments say.
- "distorted": it rests on the cited comments but misstates a position, who holds it, or its status.
- "unsupported": the cited comments do not contain what the item claims.

Answer with JSON only: {"verdict": "supported" | "distorted" | "unsupported", "why": "one line"}."""


def page_text(d, signed):
    """The whole page as plain text, every comment visible, no comment's kind or meta shown."""
    return render_for_reader(d, list(d["comments"]), labeller(d, signed), None)


def _cid(x):
    s = str(x).strip().strip("[]").strip()
    return f"c{s}" if s.isdigit() else s


def parse_items(obj):
    """Validate a redactor's answer. Returns (items, notes); bad items are dropped with a note."""
    notes = []
    if isinstance(obj, dict):
        raw = obj.get("items")
        if raw is None:
            raw = next((v for v in obj.values() if isinstance(v, list)), None)
        if raw is None and "status" in obj:
            raw = [obj]
    else:
        raw = obj
    if not isinstance(raw, list):
        raise ValueError("the answer has no list of items")
    items = []
    for i, it in enumerate(raw):
        if not isinstance(it, dict):
            notes.append(f"item {i}: not an object; dropped")
            continue
        status = str(it.get("status", "")).strip().lower()
        summary = it.get("summary")
        cites = it.get("cites", it.get("ids"))
        if status not in STATUSES:
            notes.append(f"item {i}: status {it.get('status')!r} is not one of {', '.join(STATUSES)}; dropped")
            continue
        if not isinstance(summary, str) or not summary.strip():
            notes.append(f"item {i}: no summary; dropped")
            continue
        if isinstance(cites, (str, int)):
            cites = re.split(r"[,\s]+", str(cites))
        if not isinstance(cites, list) or not [c for c in cites if str(c).strip()]:
            notes.append(f"item {i}: cites no comment ids; dropped")
            continue
        cites = list(dict.fromkeys(_cid(c) for c in cites if str(c).strip()))
        quotes = []
        for q in it.get("quotes") or []:
            if isinstance(q, dict) and str(q.get("id", "")).strip() and isinstance(q.get("text"), str) and q["text"].strip():
                quotes.append({"id": _cid(q["id"]), "text": q["text"].strip()})
            else:
                notes.append(f"item {i}: a malformed quote was dropped")
        items.append({"status": status, "summary": summary.strip(), "cites": cites, "quotes": quotes})
    return items, notes


def mechanical(item, by_id):
    """Checks that need no judge: every cited id exists; every quote is in the comment it names."""
    missing = [c for c in item["cites"] if c not in by_id]
    unfound = [q for q in item["quotes"] if q["id"] not in by_id or not locate(by_id[q["id"]]["text"], q["text"])]
    return {"ids_ok": not missing, "missing": missing, "quotes_ok": not unfound, "unfound": unfound}


def redact_one(d, model, signed):
    """One model's redaction of the page dict d. Returns (redaction, usage or None)."""
    r = {"model": model, "name": reader_entry(model)["name"], "signed": signed, "items": []}
    usage = None
    try:
        text, usage = ask_mod.ask(model, SYSTEM, page_text(d, signed), max_tokens=8000)
        items, notes = parse_items(ask_mod.extract_json(text, model))
    except Exception as e:  # one model failing should not sink the others
        r["error"] = f"{type(e).__name__}: {e}"[:600]
        return r, usage
    by_id = {c["id"]: c for c in d["comments"]}
    for it in items:
        it["check"] = mechanical(it, by_id)
    r["items"] = items
    if notes:
        r["notes"] = notes
    return r, usage


def load(page):
    return page.side(SIDE) or {"redactions": [], "usage": []}


def save(page, side):
    side["compare"] = compare(side["redactions"], [c["id"] for c in page.d["comments"]])
    page.save_side(SIDE, side)


def redact(page, models, signed=None):
    """Have each model redact the page, concurrently; a model already present is replaced.

    `signed` defaults to the page's own `signed` flag. Returns the side file as saved.
    """
    signed = page.d["flags"].get("signed", True) if signed is None else signed
    with cf.ThreadPoolExecutor(max(1, len(models))) as ex:
        done = list(ex.map(lambda m: redact_one(page.d, m, signed), models))
    side = load(page)
    fresh = {r["model"] for r, _ in done}
    side["redactions"] = [r for r in side["redactions"] if r["model"] not in fresh] + [r for r, _ in done]
    side.setdefault("usage", []).extend(u for _, u in done if u)
    save(page, side)
    return side


def _show(c, label, role=""):
    where = "on the passage" if c["target"] == "passage" else f"replying to {c['target']}"
    q = f': "{c["quote"]}"' if c.get("quote") else ""
    return f"[{c['id']}]{role} {label(c['author'])}, {where}{q}\n{c['text']}"


def judge_prompt(item, d, signed):
    """What the judge sees: the item, the comments it cites, and their parents for context."""
    by_id, label = {c["id"]: c for c in d["comments"]}, labeller(d, signed)
    out = [f"STATUS: {item['status']}", f"SUMMARY: {item['summary']}", "", "=== THE COMMENTS IT CITES ==="]
    shown = set()
    for cid in item["cites"]:
        c = by_id.get(cid)
        if not c:
            out += [f"[{cid}] (no such comment on the page)", ""]
            continue
        p = by_id.get(c["target"])
        if p and p["id"] not in shown and p["id"] not in item["cites"]:
            out += [_show(p, label, " (context: the comment replied to)"), ""]
            shown.add(p["id"])
        out += [_show(c, label), ""]
    return "\n".join(out)


def judge_one(judge, item, d, signed):
    try:
        obj, usage = ask_mod.ask_json(judge, JUDGE_SYSTEM, judge_prompt(item, d, signed), max_tokens=1000)
        verdict = str(obj.get("verdict", "")).strip().lower() if isinstance(obj, dict) else ""
        if verdict not in VERDICTS:
            return {"verdict": None, "why": f"unusable answer from the judge: {str(obj)[:200]}"}, usage
        return {"verdict": verdict, "why": " ".join(str(obj.get("why", "")).split())}, usage
    except Exception as e:
        return {"verdict": None, "why": f"{type(e).__name__}: {e}"[:300]}, None


def judge_items(page, judge):
    """Have a judge rate every item of every redaction; stores verdict and why in each check."""
    side = load(page)
    todo = [(r, it) for r in side["redactions"] for it in r.get("items", [])]
    if todo:
        with cf.ThreadPoolExecutor(min(8, len(todo))) as ex:
            done = list(ex.map(lambda t: judge_one(judge, t[1], page.d, t[0].get("signed", True)), todo))
        for (_, it), (v, u) in zip(todo, done):
            it.setdefault("check", {}).update(v, judge=judge)
            if u:
                side.setdefault("usage", []).append(u)
    save(page, side)
    return side


def jaccard(a, b):
    """|a & b| / |a | b|, or None when both are empty."""
    a, b = set(a), set(b)
    return round(len(a & b) / len(a | b), 3) if a | b else None


def compare(redactions, page_ids):
    """Overlap between redactions by the comment ids they cite (ids not on the page are ignored)."""
    ids = set(page_ids)
    ok = [r for r in redactions if not r.get("error")]
    cited = {r["model"]: {c for it in r["items"] for c in it["cites"] if c in ids} for r in ok}
    by_status = {r["model"]: {s: {c for it in r["items"] if it["status"] == s for c in it["cites"] if c in ids}
                              for s in STATUSES} for r in ok}
    pairs = [{"a": a, "b": b, "all": jaccard(cited[a], cited[b]),
              **{s: jaccard(by_status[a][s], by_status[b][s]) for s in STATUSES}}
             for a, b in itertools.combinations(cited, 2)]
    union = set().union(*cited.values()) if cited else set()
    counts = {c: sum(c in s for s in cited.values()) for c in union}
    key = lambda c: (len(c), c)
    return {
        "models": list(cited),
        "pairs": pairs,
        "core": sorted((c for c, k in counts.items() if k == len(cited)), key=key) if cited else [],
        "only_one": {c: next(m for m, s in cited.items() if c in s) for c in sorted(counts, key=key) if counts[c] == 1} if len(cited) > 1 else {},
        "uncited": round(1 - len(union) / len(ids), 3) if ids else None,
    }


def report(side):
    """A short plain-text summary of redactions.json: each redaction, its checks, and the overlap."""
    out = []
    for r in side["redactions"]:
        if r.get("error"):
            out.append(f"{r['name']:<24} ERROR {r['error'][:120]}")
            continue
        its = r["items"]
        n = lambda s: sum(it["status"] == s for it in its)
        chk = [it.get("check", {}) for it in its]
        line = (f"{r['name']:<24} {len(its):>3} items  {n('disputed')} disputed  {n('settled')} settled  "
                f"{n('unresolved')} unresolved   ids ok {sum(bool(c.get('ids_ok')) for c in chk)}/{len(its)}  "
                f"quotes ok {sum(bool(c.get('quotes_ok')) for c in chk)}/{len(its)}")
        judged = [c["verdict"] for c in chk if c.get("verdict")]
        if judged:
            line += "   " + "  ".join(f"{v} {judged.count(v)}" for v in VERDICTS)
        out.append(line)
    cmp = side.get("compare") or {}
    if cmp.get("pairs"):
        names = {r["model"]: r["name"] for r in side["redactions"]}
        f = lambda x: "  -  " if x is None else f"{x:.2f}"
        out += ["", f"{'pair (Jaccard of cited ids)':<44} {'all':>5} " + " ".join(f"{s:>10}" for s in STATUSES)]
        for p in cmp["pairs"]:
            out.append(f"{names[p['a']][:20] + ' / ' + names[p['b']][:20]:<44} {f(p['all']):>5} "
                       + " ".join(f"{f(p[s]):>10}" for s in STATUSES))
    if cmp.get("models"):
        out += ["", f"cited by every redaction: {', '.join(cmp['core']) or '(none)'}"]
        if cmp["only_one"]:
            out.append(f"cited by one only: {', '.join(cmp['only_one'])}")
        if cmp["uncited"] is not None:
            out.append(f"page comments no redaction cites: {cmp['uncited']:.0%}")
    return "\n".join(out)
