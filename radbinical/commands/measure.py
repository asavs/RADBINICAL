"""Round-over-round measures, and how late-joining readers engage the page.

    python -m radbinical measure
    python -m radbinical measure --embed mock:bow --runs some/runs --out some/data

Planted comments are not a reader's own, so they are left out of every count and share below; a
reply to a plant is still a reply, and a plant can still be the parent or see_also target that a
comment engages.

Writes <out>/rounds.jsonl, one row per run and round:

    comments        comments made that round
    share_replies   share that reply to a comment (the rest are fresh glosses on the passage)
    share_older     share whose parent or a see_also target is from round r-2 or earlier
                    (null in rounds 1 and 2, where no such layer exists)
    new_readings    readings whose first gloss in this run is from this round
    alive           readings that got a comment this round: a gloss in it, or a reply in a
                    member gloss's thread
    cumulative      distinct readings introduced in this run up to this round
    mean_length     mean characters per comment
    spans           distinct passage spans touched (a reply counts its root's span)

and <out>/joiners.jsonl, one row per reader who joined a run after its first round, by the
`joined` round in the run's row of the table (its first turn, or a person's first comment): its
comments, the share of them that reply to or cite an existing comment, the share that gloss the
passage with no see_also, and the age in rounds of the comments it engages.
Readings are clustered as by the readings command, with the same options.
"""
import argparse

from ..table import runs, write_jsonl
from .readings import add_options, build, safe


def share(k, n):
    return round(k / n, 4) if n else None


def rounds_rows(rs, members):
    reading_of = {(m["run"], m["id"]): m["reading"] for m in members}
    rnd = {(r["run"], r["id"]): r["round"] for r in rs}
    out = []
    for run in dict.fromkeys(r["run"] for r in rs):
        mine = [r for r in rs if r["run"] == run and r["kind"] != "plant"]
        first = {}
        for r in mine:
            g = reading_of.get((run, r["id"]))
            if g:
                first[g] = min(first.get(g, r["round"]), r["round"])
        for k in sorted({r["round"] for r in mine}):
            now = [r for r in mine if r["round"] == k]
            older = sum(any(rnd[(run, t)] <= k - 2 for t in targets(r)) for r in now)
            out.append({
                "run": run, "round": k, "comments": len(now),
                "share_replies": share(sum(r["parent"] is not None for r in now), len(now)),
                "share_older": share(older, len(now)) if k >= 3 else None,
                "new_readings": sum(v == k for v in first.values()),
                "alive": len({reading_of[(run, r["root"])] for r in now if (run, r["root"]) in reading_of}),
                "cumulative": sum(v <= k for v in first.values()),
                "mean_length": round(sum(len(r["text"]) for r in now) / len(now), 1),
                "spans": len({(r["start"], r["end"]) for r in now}),
            })
    return out


def targets(r):
    return ([r["parent"]] if r["parent"] else []) + list(r["see_also"])


def joiner_rows(rs, run_rows):
    """Rows for readers whose `joined` round (from the table's run rows) is after round 1."""
    rnd = {(r["run"], r["id"]): r["round"] for r in rs}
    out = []
    for run in run_rows:
        for reader in run["readers"]:
            if not reader["joined"] or reader["joined"] <= 1:
                continue
            cs = [r for r in rs if r["run"] == run["run"] and r["reader"] == reader["name"] and r["kind"] != "plant"]
            ages = [r["round"] - rnd[(run["run"], t)] for r in cs for t in targets(r)]
            out.append({
                "run": run["run"], "reader": reader["name"], "model": reader["model"], "joined": reader["joined"],
                "comments": len(cs),
                "share_engaging": share(sum(bool(targets(r)) for r in cs), len(cs)),
                "share_fresh": share(sum(not targets(r) for r in cs), len(cs)),
                "mean_age": round(sum(ages) / len(ages), 2) if ages else None,
                "max_age": max(ages) if ages else None,
                "share_older": share(sum(a >= 2 for a in ages), len(ages)),
            })
    return out


def pct(x):
    return "   -" if x is None else f"{x:4.0%}"


def main(a):
    out, rs, _, ms = build(a)
    rr, jr = rounds_rows(rs, ms), joiner_rows(rs, runs(a.runs))
    write_jsonl(out / "rounds.jsonl", rr)
    write_jsonl(out / "joiners.jsonl", jr)
    for run in dict.fromkeys(r["run"] for r in rr):
        print(f"{run}\n  round  comments  replies  older  new  alive  cumul  length  spans")
        for r in (x for x in rr if x["run"] == run):
            print(f"  {r['round']:5}  {r['comments']:8}  {pct(r['share_replies']):>7}  {pct(r['share_older']):>5}  "
                  f"{r['new_readings']:3}  {r['alive']:5}  {r['cumulative']:5}  {r['mean_length']:6.0f}  {r['spans']:5}")
        for j in (x for x in jr if x["run"] == run):
            age = "-" if j["mean_age"] is None else f"{j['mean_age']:.1f}"
            print(f"  late joiner {safe(j['reader'])} (round {j['joined']}): {j['comments']} comments, "
                  f"{pct(j['share_engaging']).strip()} engage existing comments, {pct(j['share_fresh']).strip()} fresh, "
                  f"mean age of what it engages {age} rounds")
    if not jr:
        print("No reader joined a run after its first round.")
    print(f"-> {out}")


def register(sub):
    p = sub.add_parser("measure", help="round-over-round measures and late joiners", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    add_options(p)
    p.set_defaults(f=main)
