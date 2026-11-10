"""A position statement that readers draft, annotate and amend by vote.

    python -m radbinical amend start config.json --out runs/<name>
    python -m radbinical extend runs/<name> -n 2          # ordinary annotation rounds
    python -m radbinical amend propose runs/<name>
    python -m radbinical amend vote runs/<name>
    python -m radbinical amend cycle runs/<name> -n 1     # rounds, then propose, then vote

The config holds "question", "models", the usual "flags", and optionally
"amend": {"threshold": 0.66, "max_words": 250}, "title" and "id" (the passage id; by default
amend-<question words>). One reader, the first in the order the seed gives, drafts version 1;
if its draft is unusable the next one drafts.

A proposal passes when yes / (yes + no) >= threshold and at least half the readers voted yes or
no. Passed proposals are applied higher yes share first; one that overlaps an earlier-applied
proposal, or would take the text over max_words, is not applied. Every version, proposal and
vote is kept in amendments.json beside page.json (see radbinical/amend.py).
"""
import argparse
import datetime
import json
import re
from pathlib import Path

from .. import amend
from ..config import ROOT
from ..page import Page


def show(new):
    for p in new:
        print(f"  {p['id']} by {p['author']}: {p['status']}" + (f" ({p['note']})" if p["note"] else ""))


def main(a):
    if a.step == "start":
        cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
        out = Path(a.out) if a.out else ROOT / "runs" / (
            datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + "-amend-"
            + re.sub(r"[^a-z0-9]+", "-", str(cfg.get("question", "")).lower()).strip("-")[:40])
        page = amend.start(cfg, out)
        rec = page.side("amendments")
        print(f"version 1 by {rec['drafter']}, {rec['versions'][0]['words']} words\n{page.dir / 'page.html'}")
        return
    page = Page.load(a.run)
    if a.step == "propose":
        new = amend.propose(page)
        print(f"{len(new)} proposal(s)")
        show(new)
        return
    ids = {p["id"] for p in amend.record(page)["proposals"] if p["status"] == "open"}
    if a.step == "vote":
        nv = amend.vote(page)
    else:
        new, nv = amend.cycle(page, a.n)
        print(f"{len(new)} proposal(s)")
        show(p for p in new if p["status"] == "invalid")
        ids |= {p["id"] for p in new}
    for p in page.side("amendments")["proposals"]:
        if p["id"] in ids and p["status"] == "closed":
            print(f"  {p['id']} by {p['author']}: {p['yes']} yes, {p['no']} no, {p['abstain']} abstain, "
                  + ("applied" if p["applied"] else "passed, not applied" if p["passed"] else "failed")
                  + (f" ({p['note']})" if p["note"] else ""))
    stale = [c["id"] for c in page.d["comments"] if c.get("stale")]
    print(f"version {nv['n']}, {nv['words']} words" if nv else "text unchanged",
          f"; stale comments: {', '.join(stale)}" if stale else "", f"\n{page.dir / 'page.html'}", sep="")


def register(sub):
    p = sub.add_parser("amend", help="draft a position statement and amend it by vote", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    steps = p.add_subparsers(dest="step", required=True, metavar="<step>")
    s = steps.add_parser("start", help="draft version 1 from a config")
    s.add_argument("config")
    s.add_argument("--out", help="run folder (default runs/<time>-amend-<question>)")
    for name, what in (("propose", "every reader may propose amendments"),
                       ("vote", "every reader votes on open proposals; passed ones are applied"),
                       ("cycle", "annotation rounds, then propose, then vote")):
        q = steps.add_parser(name, help=what)
        q.add_argument("run")
        if name == "cycle":
            q.add_argument("-n", type=int, default=1, help="annotation rounds before proposing (default 1)")
    p.set_defaults(f=main)
