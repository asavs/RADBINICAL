"""Case law: models rule on concrete hypotheticals, with and without the page as precedent.

A cases file `cases/<passage id>.json` is a list of
    {"id", "case": a short concrete situation, "question": yes/no or A/B, "options": ["...", "..."]}.

Each model rules on each case under two conditions: "bare" (the passage only) and "page" (the
passage and its full margins, which it may cite by id as precedent). A ruling is
    {"case", "model", "name", "condition", "rep", "option", "reason", "cites"}
with "error" (and option None) when the answer could not be used, and "bad_cites" for cited ids
that are not on the page. `summarize` turns rulings into agreement figures. Agreement measures
consistency between models; it says nothing about which ruling is right.
"""
import concurrent.futures as cf
import itertools
import json
import re
from collections import Counter
from pathlib import Path

from . import ask as ask_mod
from .page import labeller, render_for_reader

CONDITIONS = ("bare", "page")
NOTE = ("Agreement going up with the page shows the page made rulings more consistent between "
        "models, not more correct.")

SYSTEM = (
    "You are asked to rule on a hypothetical case that turns on how a passage should be read. "
    "Rule on the passage's own terms, as its author's reasoning best applies, not on your own "
    "view of what would be best. Choose exactly one of the options, even if it is close. "
    'Answer as {"option": "A", "reason": "one to three sentences", "cites": []}, '
    "with JSON only: one object, no other text."
)
PRECEDENT = (
    'Readers have annotated the passage; their comments are in the margins below. You may cite '
    'comments as precedent by listing their ids in "cites" (e.g. ["c3", "c12"]); cite only those '
    "your ruling actually relies on, or none."
)


def load_cases(path):
    """The cases in a cases file, validated. Raises ValueError naming the first problem."""
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{path}: expected a non-empty list of cases")
    ids = set()
    for i, c in enumerate(cases):
        where = f"{path}: case {i + 1}"
        if not isinstance(c, dict):
            raise ValueError(f"{where} is not an object")
        for k in ("id", "case", "question"):
            if not isinstance(c.get(k), str) or not c[k].strip():
                raise ValueError(f"{where} needs a non-empty string {k!r}")
        opts = c.get("options")
        if not isinstance(opts, list) or len(opts) < 2 or not all(isinstance(o, str) and o.strip() for o in opts) \
                or len(set(opts)) != len(opts):
            raise ValueError(f"{where} needs at least two distinct string options")
        if c["id"] in ids:
            raise ValueError(f"{where}: duplicate id {c['id']!r}")
        ids.add(c["id"])
    return cases


def letter(i):
    return chr(65 + i)


def prompt(page, case, condition):
    """The user message for one ruling."""
    d = page.d
    p = d["passage"]
    if condition == "page":
        body = PRECEDENT + "\n\n" + render_for_reader(d, list(d["comments"]), labeller(d), None)
    else:
        body = "\n".join(["=== THE PASSAGE ===", p["title"] + (f" ({p['source']})" if p.get("source") else ""), "", p["text"]])
    opts = "\n".join(f"{letter(i)}. {o}" for i, o in enumerate(case["options"]))
    return (f"{body}\n\n=== THE CASE ===\n{case['case']}\n\n=== THE QUESTION ===\n{case['question']}\n\n{opts}\n\n"
            f'Give "option" as the letter of your choice.')


def _norm(s):
    return " ".join(re.sub(r"[^\w\s]", " ", str(s).lower()).split())


def pick_option(raw, options):
    """The option a model chose: a letter ("B", "B."), a 1-based index, or the option's text
    (case and punctuation ignored). None if it matches no option."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return options[raw - 1] if 1 <= raw <= len(options) else None
    s = str(raw).strip()
    by_letter = lambda m: options[ord(m.group(1).upper()) - 65] if m and ord(m.group(1).upper()) - 65 < len(options) else None
    if re.fullmatch(r"\(?[A-Za-z]\)?[.:]?", s):
        return by_letter(re.search(r"([A-Za-z])", s))
    n = _norm(s)
    for o in options:
        if n == _norm(o):
            return o
    return by_letter(re.fullmatch(r"\(?([A-Za-z])[.):]\s+.*", s, re.S))


def validate(obj, case, condition, page_ids):
    """(ruling fields, error or None) from a model's JSON answer."""
    if not isinstance(obj, dict):
        return {"option": None, "reason": "", "cites": []}, f"expected a JSON object, got {str(obj)[:200]!r}"
    option = pick_option(obj.get("option", obj.get("choice")), case["options"])
    reason = str(obj.get("reason") or "").strip()[:1500]
    raw = obj.get("cites") or []
    if isinstance(raw, str):
        raw = re.split(r"[,\s]+", raw)
    if not isinstance(raw, list):
        raw = []
    valid = page_ids if condition == "page" else set()
    cites, bad = [], []
    for x in raw:
        x = str(x).strip("[] ")
        if x:
            (cites if x in valid else bad).append(x)
    out = {"option": option, "reason": reason, "cites": list(dict.fromkeys(cites))}
    if bad:
        out["bad_cites"] = bad
    err = None if option else f"option {str(obj.get('option'))[:100]!r} is not one of the options"
    return out, err


def rule(page, case, model, name, condition, rep, temperature=None):
    """One ruling. Returns (ruling, usage or None); never raises."""
    base = {"case": case["id"], "model": model, "name": name, "condition": condition, "rep": rep}
    usage = None
    try:
        text, usage = ask_mod.ask(model, SYSTEM, prompt(page, case, condition), 1500, temperature)
        obj = ask_mod.extract_json(text, model)
        fields, err = validate(obj, case, condition, {c["id"] for c in page.d["comments"]})
    except Exception as e:
        fields, err = {"option": None, "reason": "", "cites": []}, f"{type(e).__name__}: {e}"
    r = {**base, **fields}
    if err:
        r["error"] = err[:600]
    return r, usage


def run(page, cases, models, repeat=1, workers=8, temperature=None):
    """Every (model, case, condition, rep) ruling, asked concurrently. models: [(model, name)].
    Returns (rulings in a stable order, usage list)."""
    jobs = [(c, m, n, cond, k) for c in cases for m, n in models for cond in CONDITIONS for k in range(repeat)]
    with cf.ThreadPoolExecutor(max(1, min(workers, len(jobs)))) as ex:
        out = list(ex.map(lambda j: rule(page, *j, temperature=temperature), jobs))
    return [r for r, _ in out], [u for _, u in out if u is not None]


def _modal(options_chosen, order):
    """The most chosen option, ties broken by the order the options are listed in."""
    n = Counter(options_chosen)
    return max(n, key=lambda o: (n[o], -order.index(o))) if n else None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


def summarize(cases, rulings):
    """Agreement figures from rulings.

    For each condition: per case, `agreement` is the share of models whose ruling (their modal
    option over reps) is the most common one, and `pairwise` the share of model pairs that agree;
    both are then averaged over cases. `self_consistency` is the mean share of a model's reps on
    a case that match its own modal option (None with one rep). For "page": how many rulings cite
    precedent and which comments are cited most. `changed`: (model, case) pairs whose ruling
    differs between bare and page.
    """
    order = {c["id"]: c["options"] for c in cases}
    good = [r for r in rulings if not r.get("error") and r["case"] in order]
    out = {"conditions": {}, "note": NOTE}
    modal = {}  # (condition, case, name) -> option
    for cond in CONDITIONS:
        rs = [r for r in good if r["condition"] == cond]
        per_case, selfc, agree, pairwise = {}, [], [], []
        for c in cases:
            by_model = {}
            for r in rs:
                if r["case"] == c["id"]:
                    by_model.setdefault(r["name"], []).append(r["option"])
            for name, opts in by_model.items():
                m = modal[(cond, c["id"], name)] = _modal(opts, c["options"])
                if len(opts) > 1:
                    selfc.append(opts.count(m) / len(opts))
            choices = [modal[(cond, c["id"], n)] for n in by_model]
            if not choices:
                continue
            counts = Counter(choices)
            pairs = list(itertools.combinations(choices, 2))
            agree.append(max(counts.values()) / len(choices))
            pairwise.append(sum(a == b for a, b in pairs) / len(pairs) if pairs else None)
            per_case[c["id"]] = {
                "models": len(choices),
                "counts": {o: counts[o] for o in c["options"] if counts[o]},
                "agreement": round(agree[-1], 4),
                "pairwise": None if pairwise[-1] is None else round(pairwise[-1], 4),
            }
        s = {"rulings": len([r for r in rulings if r["condition"] == cond]),
             "errors": len([r for r in rulings if r["condition"] == cond and r.get("error")]),
             "agreement": _mean(agree),
             "pairwise": _mean(pairwise),
             "self_consistency": _mean(selfc), "per_case": per_case}
        if cond == "page":
            cited = Counter(i for r in rs for i in r["cites"])
            s["citing"] = sum(1 for r in rs if r["cites"])
            s["valid"] = len(rs)
            s["bad_cites"] = sum(len(r.get("bad_cites", [])) for r in rulings if r["condition"] == cond)
            s["precedents"] = [[i, n] for i, n in sorted(cited.items(), key=lambda x: (-x[1], int(x[0][1:]) if x[0][1:].isdigit() else 0))]
        first = next((r for r in rulings if r["condition"] == cond and r.get("error")), None)
        if first:
            s["first_error"] = f"{first['name']} on {first['case']}: {first['error'][:200]}"
        out["conditions"][cond] = s
    pairs = sorted({(c, n) for (_, c, n) in modal})
    both = [(c, n) for c, n in pairs if ("bare", c, n) in modal and ("page", c, n) in modal]
    which = [{"case": c, "name": n, "bare": modal[("bare", c, n)], "page": modal[("page", c, n)]}
             for c, n in both if modal[("bare", c, n)] != modal[("page", c, n)]]
    out["changed"] = {"count": len(which), "of": len(both), "which": which}
    return out


def report(cases, summary, repeat):
    """The printed report, as a string."""
    labels = {c["id"]: {o: letter(i) for i, o in enumerate(c["options"])} for c in cases}
    lines = []
    f = lambda x: "  -" if x is None else f"{x:.2f}"
    for cond in CONDITIONS:
        s = summary["conditions"][cond]
        lines.append(f"\n{cond}: {s['rulings']} rulings, {s['errors']} errors; "
                     f"agreement {f(s['agreement'])}, mean pairwise {f(s['pairwise'])}"
                     + (f", self-consistency {f(s['self_consistency'])} over {repeat} reps" if repeat > 1 else ""))
        if s.get("first_error"):
            lines.append(f"  first error: {s['first_error']}")
        for cid, v in s["per_case"].items():
            split = " ".join(f"{labels[cid][o]}:{n}" for o, n in v["counts"].items())
            lines.append(f"  {cid:<28} agreement {f(v['agreement'])}  pairwise {f(v['pairwise'])}  ({split})")
        if cond == "page":
            lines.append(f"  {s['citing']} of {s['valid']} valid rulings cite precedent"
                         + (f"; {s['bad_cites']} cited ids not on the page were dropped" if s["bad_cites"] else ""))
            if s["precedents"]:
                lines.append("  most cited: " + ", ".join(f"{i} ({n})" for i, n in s["precedents"][:8]))
    ch = summary["changed"]
    lines.append(f"\nchanged ruling between bare and page: {ch['count']} of {ch['of']} (model, case) pairs")
    for w in ch["which"]:
        lines.append(f"  {w['case']:<28} {w['name']}: {labels[w['case']][w['bare']]} -> {labels[w['case']][w['page']]}")
    lines.append("\n" + summary["note"])
    return "\n".join(lines)
