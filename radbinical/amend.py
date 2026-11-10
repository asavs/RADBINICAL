"""Amendment: readers draft a short position statement, annotate it, and amend it by vote.

The statement is the page's passage. Its whole history lives in the side file amendments.json:

    {"question", "threshold", "max_words", "drafter",
     "versions":  [{"n", "text", "from_proposals": [ids], "after_round", "words"}],
     "proposals": [{"id", "version", "author", "quote", "replacement", "reason", "cites",
                    "start", "end", "status", "votes": [{"reader", "vote", "why"}],
                    "yes", "no", "abstain", "passed", "applied", "note"}],
     "log":   [{"step", "version", "reader", "model", "error"?, ...}],
     "usage": [usage dicts of every call]}

A proposal's `status` is "open" (waiting for votes), "invalid" (never put to the vote; `note`
says why) or "closed". `passed` and `applied` are None while open. Failed proposals and every
vote, with its reason, stay in the record.

Steps:
    start(cfg, out)   one reader, chosen by the seed, drafts version 1 (the next in the seeded
                      order drafts if one fails)
    propose(page)     every reader may propose exact replacements of quoted spans
    vote(page)        every reader votes on every open proposal; passed ones are applied
    cycle(page, n)    n annotation rounds, then propose and vote

When the text changes, each comment on the passage is re-anchored (see `reanchor`); a comment
whose quoted words are gone keeps its record and gains `stale`: the version that lost them.

`mock:` readers make no call: the user message carries a `MOCK_REPLY:` line with a
deterministic placeholder answer, so a whole cycle runs offline.
"""
import concurrent.futures as cf
import datetime
import json
import random
import re
import sys
from pathlib import Path

from .anchoring import fold, locate
from .ask import ask, extract_json
from .config import DEFAULT_FLAGS
from .page import Page, cast_of, reader_entry, render_for_reader
from .prompts import system_prompt
from .providers import split_model
from .rounds import run_layers
from .site import render

DEFAULTS = {"threshold": 0.66, "max_words": 250}
VOTES = ("yes", "no", "abstain")


def words(text):
    return len(text.split())


def tidy(text):
    """Paragraphs separated by one blank line, whitespace inside each collapsed."""
    return "\n\n".join(" ".join(p.split()) for p in re.split(r"\n\s*\n", text or "") if p.strip())


def labels(d):
    """How readers are named to each other: themselves when signed, else Reader A, Reader B..."""
    if d["flags"]["signed"]:
        return lambda a: a
    names = {r["name"]: f"Reader {chr(65 + i)}" for i, r in enumerate(d["readers"])}
    return lambda a: names.get(a, "Reader")


def order(d):
    """The readers in the order the seed gives."""
    readers = d["readers"][:]
    random.Random(f"{d['flags']['seed']}-draft").shuffle(readers)
    return readers


# --- calls ---------------------------------------------------------------------------------

def _call(rec, d, reader, step, version, system, user, mock):
    """One call whose answer should hold JSON. Returns (the parsed answer or None, a log entry).
    The call's usage is kept even when its answer does not parse."""
    if split_model(reader["model"])[0] == "mock":
        user += "\nMOCK_REPLY: " + json.dumps(mock, ensure_ascii=False)
    entry = {"step": step, "version": version, "reader": reader["name"], "model": reader["model"]}
    try:
        text, usage = ask(reader["model"], system, user,
                          reader.get("max_tokens") or d["flags"]["max_tokens"], d["flags"]["temperature"])
        rec["usage"].append({**usage, "step": step, "reader": reader["name"]})
        obj = extract_json(text, reader["name"])
    except Exception as e:  # one reader failing should not sink the step
        obj, entry["error"] = None, f"{type(e).__name__}: {e}"[:600]
    return obj, entry


def _each(rec, d, step, version, make):
    """Ask every reader at once; make(reader) -> (system, user, mock).
    Returns [(reader, parsed answer or None, log entry)] in reader order."""
    def one(r):
        return _call(rec, d, r, step, version, *make(r))
    with cf.ThreadPoolExecutor(max(1, len(d["readers"]))) as ex:
        results = list(ex.map(one, d["readers"]))
    out = []
    for r, (obj, entry) in zip(d["readers"], results):
        rec["log"].append(entry)
        out.append((r, obj, entry))
    return out


# --- drafting ------------------------------------------------------------------------------

DRAFT_SYSTEM = (
    "You are drafting a short position statement on a question. Other readers will then annotate it, "
    "propose amendments to its wording and vote on them, so write what you think, plainly, in at most "
    "{max_words} words. Separate paragraphs with a blank line. Answer as JSON: {{\"statement\": \"...\"}}."
)


def _mock_draft(question, name):
    return {"statement": (
        f"[mock] A statement by {name} on the question. The question asks: {question.rstrip('?.')}. "
        "The short answer is yes, with conditions that matter more than the answer itself. "
        "Whoever holds the power to decide should also carry the duty to explain the decision. "
        "Where the evidence is thin, the decision should be easy to revisit.")}


def start(cfg, out, group=None):
    """Make a page whose passage is a drafted statement on cfg["question"]. Returns the Page.

    Readers are tried in the seeded order until one gives a statement within max_words; every
    attempt is logged. Exits if none does.
    """
    question = str(cfg.get("question") or "").strip()
    if not question:
        sys.exit("the config needs a \"question\"")
    settings = {**DEFAULTS, **(cfg.get("amend") or {})}
    flags = {**DEFAULT_FLAGS, **cfg.get("flags", {})}
    unknown = set(flags) - set(DEFAULT_FLAGS)
    if unknown:
        sys.exit(f"unknown flag(s) in config: {', '.join(sorted(unknown))}")
    readers = [reader_entry(m) for m in cfg["models"]]
    names = [r["name"] for r in readers]
    if len(set(names)) != len(names):
        sys.exit("reader names must be unique; give duplicates a distinct \"name\" in the config")
    out = Path(out)
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:40]
    d = {
        "passage": {"id": cfg.get("id") or f"amend-{slug}", "title": cfg.get("title") or question,
                    "source": "", "text": "", "version": 1},
        "readers": readers, "cast": cast_of(readers), "group": group or out.name,
        "flags": flags, "comments": [], "log": [], "counter": 0, "layers_done": 0,
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    rec = {"question": question, "threshold": settings["threshold"], "max_words": settings["max_words"],
           "drafter": None, "versions": [], "proposals": [], "log": [], "usage": []}
    system = DRAFT_SYSTEM.format(max_words=settings["max_words"])
    for r in order(d):
        obj, entry = _call(rec, d, r, "draft", 1, system, f"The question: {question}\n\nWrite the statement.",
                           _mock_draft(question, r["name"]))
        rec["log"].append(entry)
        text = tidy(obj.get("statement") if isinstance(obj, dict) and isinstance(obj.get("statement"), str) else "")
        if obj is not None and not text:
            entry["error"] = "no statement in the answer"
        elif text and words(text) > settings["max_words"]:
            entry["error"] = f"statement has {words(text)} words, over max_words {settings['max_words']}"
        elif text:
            rec["drafter"] = r["name"]
            break
    if not rec["drafter"]:
        sys.exit("no reader drafted a usable statement: " + "; ".join(f"{e['reader']}: {e.get('error')}" for e in rec["log"]))
    d["passage"].update(text=text, source=f"Position statement drafted by {rec['drafter']}, amended by vote")
    rec["versions"].append({"n": 1, "text": text, "from_proposals": [], "after_round": 0, "words": words(text)})
    out.mkdir(parents=True, exist_ok=True)
    page = Page(d, out)
    d["prompt_example"] = system_prompt(d, names[0], lambda x: x)
    page.save()
    page.save_side("amendments", rec)
    render(out)
    return page


def record(page):
    rec = page.side("amendments")
    if not isinstance(rec, dict) or not rec.get("versions"):
        sys.exit(f"{page.dir} has no amendments.json; start it with `amend start`")
    rec.setdefault("log", [])
    rec.setdefault("usage", [])
    rec.setdefault("proposals", [])
    return rec


def _stale_note(d):
    stale = [c["id"] for c in d["comments"] if c.get("stale")]
    return (f"\n(Comments {', '.join(stale)} quote words that an amendment has since removed from the statement.)\n"
            if stale else "")


def _context(rec, d, me):
    v = rec["versions"][-1]["n"]
    return (f"The question: {rec['question']}\nThe passage below is version {v} of a position statement on it.\n\n"
            + render_for_reader(d, d["comments"], labels(d), me) + _stale_note(d))


# --- proposing -----------------------------------------------------------------------------

PROPOSE_SYSTEM = (
    "You are one of {n} readers of a short position statement. The readers have annotated it in the margins. "
    "You may now propose amendments to its wording. Each amendment replaces one exact span of the current text: "
    "`quote` is copied exactly from the statement and must occur in it only once; `replacement` is the new words "
    "(an empty string deletes the span; to insert, quote a few words and repeat them in the replacement with the new "
    "words added); `reason` says why; `cites` lists the ids of comments that motivate it (may be empty). "
    "Every reader then votes on every amendment. One passes when at least {threshold:.0%} of the yes and no votes "
    "are yes and at least half the readers vote yes or no. Of two passed amendments that touch the same words, only "
    "the better supported is applied. The statement must stay within {max_words} words. Propose nothing if you "
    "would keep the text as it is. Answer as JSON: "
    "{{\"amendments\": [{{\"quote\": \"...\", \"replacement\": \"...\", \"reason\": \"...\", \"cites\": [\"c3\"]}}]}}."
)


def _mock_proposals(text, d, name, version):
    rng = random.Random(f"{name}-propose-{version}-{len(d['comments'])}")
    if rng.random() < 0.4:
        return {"amendments": []}
    sents = [s for s in re.split(r"(?<=[.;])\s+", text) if len(s.split()) >= 6]
    if not sents:
        return {"amendments": []}
    w = rng.choice(sents).split()
    a = rng.randrange(0, len(w) - 4)
    quote = " ".join(w[a:a + rng.randint(3, 5)])
    replacement = rng.choice(["", quote + " [mock] in most cases", "[mock] reworded"])
    ids = [c["id"] for c in d["comments"]]
    return {"amendments": [{"quote": quote, "replacement": replacement, "reason": "[mock] tighter this way.",
                            "cites": rng.sample(ids, min(len(ids), 1))}]}


def check(text, raw, known_ids):
    """Validate one proposed amendment against the current text. Returns (fields, ok, note).

    `ok` is False for a proposal that cannot go to the vote; `note` says why, and also records
    cited ids that do not exist (dropped from `cites`).
    """
    if not isinstance(raw, dict):
        return {"quote": "", "replacement": "", "reason": "", "cites": []}, False, "not an object with quote and replacement"
    quote, rep = raw.get("quote"), raw.get("replacement")
    cites = [str(c).strip("[] ") for c in raw.get("cites")] if isinstance(raw.get("cites"), list) else []
    p = {"quote": quote if isinstance(quote, str) else "", "replacement": rep.strip() if isinstance(rep, str) else "",
         "reason": str(raw.get("reason") or "").strip(), "cites": [c for c in cites if c in known_ids]}
    dropped = [c for c in cites if c not in known_ids]
    extra = f"unknown cites dropped: {', '.join(dropped)}" if dropped else None

    def out(ok, why=None):
        return p, ok, "; ".join(x for x in (why, extra) if x) or None

    if not isinstance(quote, str) or not quote.strip():
        return out(False, "no quote")
    if not isinstance(rep, str):
        return out(False, "no replacement (an empty string deletes)")
    span = locate(text, quote)
    if not span:
        return out(False, "quote not found in the statement")
    if locate(text[span[1]:], quote):
        return out(False, "quote occurs more than once in the statement")
    p.update(quote=text[span[0]:span[1]], start=span[0], end=span[1])
    if fold(p["replacement"])[0] == fold(p["quote"])[0]:
        return out(False, "replacement is the same as the quote")
    return out(True)


def propose(page):
    """Ask every reader for amendments to the current version. Returns the new proposal records."""
    d, rec = page.d, record(page)
    v = rec["versions"][-1]
    known = {c["id"] for c in d["comments"]}
    system = PROPOSE_SYSTEM.format(n=len(d["readers"]), threshold=rec["threshold"], max_words=rec["max_words"])
    answers = _each(rec, d, "propose", v["n"], lambda r: (
        system, _context(rec, d, r["name"]), _mock_proposals(v["text"], d, r["name"], v["n"])))
    new = []
    for r, obj, entry in answers:
        if obj is None:
            continue
        items = obj.get("amendments") if isinstance(obj, dict) else obj
        if not isinstance(items, list):
            entry["error"] = "no list of amendments in the answer"
            continue
        entry["proposals"] = len(items)
        for raw in items:
            p, ok, note = check(v["text"], raw, known)
            p = {"id": f"p{len(rec['proposals']) + 1}", "version": v["n"], "author": r["name"], **p,
                 "status": "open" if ok else "invalid", "votes": [], "yes": 0, "no": 0, "abstain": 0,
                 "passed": None if ok else False, "applied": None if ok else False, "note": note}
            rec["proposals"].append(p)
            new.append(p)
    page.save_side("amendments", rec)
    return new


# --- voting and applying -------------------------------------------------------------------

VOTE_SYSTEM = (
    "You are one of {n} readers of a short position statement. Readers have annotated it and proposed amendments "
    "to its wording. Vote on every proposed amendment: yes, no or abstain, each with a one-line reason. You may vote "
    "on your own. An amendment passes when at least {threshold:.0%} of the yes and no votes are yes and at least half "
    "the readers vote yes or no. Answer as JSON: "
    "{{\"votes\": [{{\"id\": \"p1\", \"vote\": \"yes\", \"why\": \"...\"}}]}}."
)


def _ballot(props, label, me):
    out = ["", "=== PROPOSED AMENDMENTS ==="]
    for p in props:
        who = label(p["author"]) + (" (you)" if p["author"] == me else "")
        change = (f'delete "{p["quote"]}"' if not p["replacement"]
                  else f'replace "{p["quote"]}" with "{p["replacement"]}"')
        out.append(f"[{p['id']}] by {who}: {change}")
        if p["reason"]:
            out.append(f"    reason: {p['reason']}")
        if p["cites"]:
            out.append(f"    cites: {', '.join(p['cites'])}")
    return "\n".join(out)


def _mock_votes(props, name):
    rng = random.Random(f"{name}-vote-" + ",".join(p["id"] for p in props))
    return {"votes": [{"id": p["id"], "vote": rng.choices(VOTES, (6, 3, 1))[0], "why": "[mock] on balance."} for p in props]}


def tally(votes, n_readers, threshold):
    """(yes, no, abstain, passed): passed when yes/(yes+no) >= threshold and at least half the
    readers voted yes or no."""
    yes = sum(v["vote"] == "yes" for v in votes)
    no = sum(v["vote"] == "no" for v in votes)
    abstain = sum(v["vote"] == "abstain" for v in votes)
    cast = yes + no
    passed = cast > 0 and 2 * cast >= n_readers and yes >= threshold * cast - 1e-9
    return yes, no, abstain, passed


def apply(text, passed, max_words):
    """Apply passed proposals to `text` in a fixed order: higher yes share first, then more yes
    votes, then earlier id. One that overlaps a proposal applied before it, or that would take
    the text over max_words, is not applied. Sets `applied` and `note` on each.
    Returns (new text, edits as [(start, end, replacement)] in text order)."""
    ranked = sorted(passed, key=lambda p: (-p["yes"] / (p["yes"] + p["no"]), -p["yes"], int(p["id"][1:])))
    edits, owner = [], {}
    for p in ranked:
        s, e = p["start"], p["end"]
        clash = next((owner[x] for x in edits if s < x[1] and x[0] < e), None)
        if clash:
            p["applied"], p["note"] = False, f"overlaps {clash}, applied before it"
            continue
        trial = sorted(edits + [(s, e, p["replacement"])])
        n = words(splice(text, trial))
        if n > max_words:
            p["applied"], p["note"] = False, f"would make the statement {n} words, over max_words {max_words}"
            continue
        edits = trial
        owner[(s, e, p["replacement"])] = p["id"]
        p["applied"] = True
    return splice(text, edits), edits


def splice(text, edits, raw=False):
    """Text with each (start, end, replacement) put in place; edits sorted and not overlapping.
    Tidied (see `tidy`) unless raw."""
    out, at = [], 0
    for s, e, rep in edits:
        out += [text[at:s], rep]
        at = e
    joined = "".join(out + [text[at:]])
    return joined if raw else tidy(joined)


def shift(p, edits, end_side):
    """Where position p of the old text lands in the raw splice. A position inside a replaced
    span goes to the start of the replacement, or its end when end_side."""
    delta = 0
    for s, e, rep in edits:
        if e <= p:
            delta += len(rep) - (e - s)
        elif s < p:
            return s + delta + (len(rep) if end_side else 0)
    return p + delta


def untangle(raw, new, p, end_side):
    """Position p of `raw` in `new` == tidy(raw), found by counting non-space characters. A start
    lands on the next non-space character, an end just after the last one before it."""
    k = sum(not ch.isspace() for ch in raw[:p])
    seen = 0
    for i, ch in enumerate(new):
        if seen == k and (end_side or not ch.isspace()):
            return i
        seen += not ch.isspace()
    return len(new)


def reanchor(comments, old, edits, new, version):
    """Recompute start/end of each comment on the passage after `edits` turned `old` into `new`.

    A comment keeps its place when its quoted words are still where the edits moved them; else
    its quote is looked for anywhere in the new text; else it is marked `stale: version` and
    points at the words that replaced its own. Already-stale comments only move.
    """
    raw = splice(old, edits, raw=True)
    for c in comments:
        if c["target"] != "passage":
            continue
        quote = c.get("quote") or old[c["start"]:c["end"]]
        s = untangle(raw, new, shift(c["start"], edits, False), False)
        e = max(s, untangle(raw, new, shift(c["end"], edits, True), True))
        if c.get("stale") or fold(new[s:e])[0].strip() == fold(quote)[0].strip():
            c["start"], c["end"] = s, e
            continue
        span = locate(new, quote)
        if span:
            c["start"], c["end"] = span
        else:
            c["start"], c["end"], c["stale"] = s, e, version


def vote(page):
    """Every reader votes on every open proposal; passed ones are applied. Returns the new
    version record, or None when the text did not change."""
    d, rec = page.d, record(page)
    v = rec["versions"][-1]
    props = [p for p in rec["proposals"] if p["status"] == "open"]
    for p in props:
        if p["version"] != v["n"] or v["text"][p["start"]:p["end"]] != p["quote"]:
            p.update(status="invalid", passed=False, applied=False, note=f"made on version {p['version']}; the text has changed")
    props = [p for p in props if p["status"] == "open"]
    if not props:
        page.save_side("amendments", rec)
        return None
    label = labels(d)
    system = VOTE_SYSTEM.format(n=len(d["readers"]), threshold=rec["threshold"])
    answers = _each(rec, d, "vote", v["n"], lambda r: (
        system, _context(rec, d, r["name"]) + _ballot(props, label, r["name"]), _mock_votes(props, r["name"])))
    by_id = {p["id"]: p for p in props}
    for r, obj, entry in answers:
        if obj is None:
            continue
        items = obj.get("votes") if isinstance(obj, dict) else obj
        if not isinstance(items, list):
            entry["error"] = "no list of votes in the answer"
            continue
        bad, done = [], set()
        for x in items:
            pid = str(x.get("id", "")).strip("[] ") if isinstance(x, dict) else ""
            choice = str(x.get("vote", "")).strip().lower() if isinstance(x, dict) else ""
            if pid not in by_id or pid in done or choice not in VOTES:
                bad.append(json.dumps(x, ensure_ascii=False)[:120])
                continue
            done.add(pid)
            by_id[pid]["votes"].append({"reader": r["name"], "vote": choice, "why": str(x.get("why") or "").strip()[:500]})
        entry["votes"] = len(done)
        if bad:
            entry["error"] = "votes not counted: " + "; ".join(bad)
    n = len(d["readers"])
    for p in props:
        p["yes"], p["no"], p["abstain"], p["passed"] = tally(p["votes"], n, rec["threshold"])
        p["status"] = "closed"
        if not p["passed"]:
            p["applied"] = False
    passed = [p for p in props if p["passed"]]
    new_text, edits = apply(v["text"], passed, rec["max_words"])
    if not edits:
        page.save_side("amendments", rec)
        return None
    nv = {"n": v["n"] + 1, "text": new_text, "from_proposals": [p["id"] for p in passed if p["applied"]],
          "after_round": d["layers_done"], "words": words(new_text)}
    rec["versions"].append(nv)
    reanchor(d["comments"], v["text"], edits, new_text, nv["n"])
    d["passage"]["text"], d["passage"]["version"] = new_text, nv["n"]
    page.save()
    page.save_side("amendments", rec)
    render(page.dir)
    return nv


def cycle(page, rounds=1):
    """`rounds` annotation rounds, then propose, then vote. Returns (proposals, new version or None)."""
    if rounds > 0:
        page.d.pop("at_rest", None)
        run_layers(page, rounds)
    return propose(page), vote(page)
