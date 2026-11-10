"""Readings: glosses on the same words that say the same thing, gathered across runs.

A gloss is a top-level comment (one on the passage, in any round); planted comments are left out.
Within one passage, every gloss from every run is embedded, and glosses are clustered:

1. Overlap of two glosses' spans is the shared length over the shorter span's length (0..1).
2. Similarity of a pair is the cosine of their embeddings if overlap >= min_overlap, else 0.
3. Average-link agglomerative clustering: start with one cluster per gloss; repeatedly merge
   the two clusters whose mean pairwise similarity is highest, while it is >= threshold.

A cluster is a reading. Its representative is the medoid (the member with the highest mean
cosine to the other members). Its models are canonical ids, so one model routed two ways counts
once. The default threshold depends on the embedding model
(THRESHOLDS); cosines from different models are not on one scale.

A fork's copies of its source's glosses are members of the source's readings, marked
`inherited`, and are not clustered or counted again (see `readings`).

Reply counts over a reading are computed from its members' threads and see_also pointers. What
is counted is structural only: direct replies, all replies below, who replied, whether a
member's author later replied in its own thread, and how often members are cited. Whether a
reply challenges a reading or its author withdraws it is not judged here.
"""
from collections import defaultdict
from itertools import combinations

from .embed import cosine, embed
from .providers import canonical

THRESHOLDS = {"mock": 0.3}   # per provider prefix
THRESHOLD = 0.8              # for real embedding models
MIN_OVERLAP = 0.5


def default_threshold(model):
    head, sep, _ = model.partition(":")
    return THRESHOLDS.get(head, THRESHOLD) if sep else THRESHOLD


def overlap(a, b):
    """Shared length of two (start, end) spans over the shorter one's length."""
    shared = min(a[1], b[1]) - max(a[0], b[0])
    short = min(a[1] - a[0], b[1] - b[0])
    return max(shared, 0) / short if short > 0 else 0.0


def glosses(rows):
    return [r for r in rows if r["parent"] is None and r.get("kind") != "plant"]


def cluster(items, vectors, threshold, min_overlap):
    """Average-link clustering of items (each with start, end) -> list of clusters, each a sorted
    list of indices into items."""
    n = len(items)
    sim = [[0.0] * n for _ in range(n)]
    for i, j in combinations(range(n), 2):
        if overlap((items[i]["start"], items[i]["end"]), (items[j]["start"], items[j]["end"])) >= min_overlap:
            sim[i][j] = sim[j][i] = cosine(vectors[i], vectors[j])
    clusters = [[i] for i in range(n)]

    def link(a, b):
        return sum(sim[i][j] for i in a for j in b) / (len(a) * len(b))

    while len(clusters) > 1:
        best, pair = None, None
        for a, b in combinations(range(len(clusters)), 2):
            s = link(clusters[a], clusters[b])
            if best is None or s > best:
                best, pair = s, (a, b)
        if best < threshold:
            break
        a, b = pair
        clusters[a] = clusters[a] + clusters[b]
        del clusters[b]
    return [sorted(c) for c in clusters]


def threads(rows):
    """(children, cited_by): comment key -> list of rows replying to it / citing it in see_also.
    A comment key is (run, id)."""
    children, cited = defaultdict(list), defaultdict(list)
    for r in rows:
        if r["parent"]:
            children[(r["run"], r["parent"])].append(r)
        for s in r["see_also"]:
            cited[(r["run"], s)].append(r)
    return children, cited


def descendants(key, children):
    out, stack = [], list(children.get(key, []))
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(children.get((c["run"], c["id"]), []))
    return out


def copied(rows):
    """{(fork, id): (source run, id)} for the glosses a fork copied from a run that is among rows."""
    keys = {(r["run"], r["id"]) for r in rows}
    return {(g["run"], g["id"]): (g["lineage"], g["id"]) for g in glosses(rows)
            if g.get("inherited") and (g["lineage"], g["id"]) in keys}


def member(rid, g, **extra):
    return {"reading": rid, "passage": g["passage"], "run": g["run"], "group": g["group"], "cast": g["cast"],
            "id": g["id"], "reader": g["reader"], "model": g["model"], "round": g["round"],
            "start": g["start"], "end": g["end"], **extra}


def readings(rows, model, threshold=None, min_overlap=MIN_OVERLAP, cache_dir=None):
    """-> (readings, members). See the module docstring for the method.

    A gloss a fork copied from its source is not clustered again: it is listed among the members
    with `inherited: true` under its original's reading, and counts toward none of the reading's
    figures except the replies made to it in the fork.
    """
    threshold = default_threshold(model) if threshold is None else threshold
    children, cited = threads(rows)
    copies = copied(rows)
    by_key = {(r["run"], r["id"]): r for r in rows}
    by_passage = defaultdict(list)
    for g in glosses(rows):
        if (g["run"], g["id"]) not in copies:
            by_passage[g["passage"]].append(g)
    found, members, reading_of = [], [], {}
    for passage in sorted(by_passage):
        items = by_passage[passage]
        vectors = embed([g["text"] for g in items], model, cache_dir)
        groups = cluster(items, vectors, threshold, min_overlap)
        groups.sort(key=lambda c: (min(items[i]["start"] for i in c), -len(c), c[0]))
        for k, c in enumerate(groups, 1):
            rid = f"{passage}/r{k}"
            mean = {i: (sum(cosine(vectors[i], vectors[j]) for j in c if j != i) / (len(c) - 1) if len(c) > 1 else 1.0)
                    for i in c}
            mi = max(c, key=lambda i: (mean[i], -i))
            found.append((rid, passage, [items[i] for i in c], items[mi]))
            for i in c:
                reading_of[(items[i]["run"], items[i]["id"])] = rid
                members.append(member(rid, items[i], cos_to_medoid=round(cosine(vectors[i], vectors[mi]), 4)))
    extra = defaultdict(list)
    for key in copies:
        src, seen = copies[key], {key}
        while src in copies and src not in seen:
            seen.add(src)
            src = copies[src]
        if src in reading_of:
            extra[reading_of[src]].append(by_key[key])
            members.append(member(reading_of[src], by_key[key], inherited=True))
    out = [reading_row(rid, passage, ms, medoid, children, cited, extra[rid]) for rid, passage, ms, medoid in found]
    return out, members


def reading_row(rid, passage, ms, medoid, children, cited, copies=()):
    """The row for one reading from its members `ms`. Replies are counted below the members and
    below `copies` (forks' copies of members), leaving out comments a fork copied."""
    first = {}
    for m in ms:
        first[m["run"]] = min(first.get(m["run"], m["round"]), m["round"])
    direct = replies = cites = author_back = 0
    repliers = set()
    fresh = lambda xs: [x for x in xs if not x.get("inherited")]
    for m in list(ms) + list(copies):
        key = (m["run"], m["id"])
        below = fresh(descendants(key, children))
        direct += len(fresh(children.get(key, [])))
        replies += len(below)
        cites += len(fresh(cited.get(key, [])))
        repliers |= {d["reader"] for d in below if d["reader"] != m["reader"]}
        author_back += any(d["reader"] == m["reader"] for d in below)
    return {
        "id": rid, "passage": passage, "start": min(m["start"] for m in ms), "end": max(m["end"] for m in ms),
        "size": len(ms),
        "representative": {k: medoid[k] for k in ("run", "id", "reader", "model", "round", "quote", "text")},
        "models": sorted({canonical(m["model"]) if m["model"] else m["reader"] for m in ms}),
        "runs": sorted(first), "groups": sorted({m["group"] for m in ms}), "casts": sorted({m["cast"] for m in ms}),
        "first_round": first,
        "direct_replies": direct, "replies": replies, "cited": cites,
        "other_repliers": sorted(repliers), "author_replied": author_back,
    }


# ---- noise floor ----------------------------------------------------------------------------

def presence(members, unit, round1=False):
    """unit value -> set of reading ids with a member in that unit (optionally round 1 only)."""
    out = defaultdict(set)
    for m in members:
        if not m.get("inherited") and (not round1 or m["round"] == 1):
            out[m[unit]].add(m["reading"])
    return out


def recurrence(sets, units):
    """Shares of readings (appearing in any of units) found in all units, in 2 or more, in exactly 1,
    and the mean pairwise Jaccard of the units' reading sets."""
    count = defaultdict(int)
    for u in units:
        for r in sets.get(u, ()):
            count[r] += 1
    n = len(count)
    pairs = []
    for a, b in combinations(units, 2):
        A, B = sets.get(a, set()), sets.get(b, set())
        pairs.append(len(A & B) / len(A | B) if A | B else 0.0)

    def share(k):
        return round(k / n, 4) if n else None
    k_all = sum(1 for v in count.values() if v == len(units))
    k_2 = sum(1 for v in count.values() if v >= 2)
    k_1 = sum(1 for v in count.values() if v == 1)
    return {"readings": n, "in_all": k_all, "in_2plus": k_2, "in_1": k_1,
            "share_all": share(k_all), "share_2plus": share(k_2), "share_1": share(k_1),
            "jaccard": round(sum(pairs) / len(pairs), 4) if pairs else None}


def noise(members, run_rows):
    """Rows of the noise floor: one per group with two or more runs (units = runs), and one per
    passage with two or more casts (units = casts, pooling each cast's runs)."""
    out = []
    groups = defaultdict(list)
    for r in run_rows:
        groups[(r["passage"], r["group"])].append(r["run"])
    for (passage, group), units in sorted(groups.items()):
        if len(units) >= 2:
            out.append({"scope": "group", "passage": passage, "key": group, "units": units,
                        "all_rounds": recurrence(presence(members, "run"), units),
                        "round1": recurrence(presence(members, "run", True), units)})
    casts = defaultdict(set)
    for r in run_rows:
        casts[r["passage"]].add(r["cast"])
    for passage, cs in sorted(casts.items()):
        if len(cs) >= 2:
            ms = [m for m in members if m["passage"] == passage]
            units = sorted(cs)
            out.append({"scope": "casts", "passage": passage, "key": passage, "units": units,
                        "all_rounds": recurrence(presence(ms, "cast"), units),
                        "round1": recurrence(presence(ms, "cast", True), units)})
    return out
