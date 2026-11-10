"""Add a person's comments to a page, check submissions, or print a blank one to fill in.

    python -m radbinical human template runs/<dir>            # the page and a starter JSON
    python -m radbinical human template runs/<dir> --blind    # the passage alone
    python -m radbinical human check humans/                  # validate; exit 1 on any problem
    python -m radbinical human add runs/<dir> --file humans/<dir>/<name>.json

A submission is humans/<run>/<name>.json and is checked against runs/<run>/page.json:
    {"name": "...", "blind": false, "saw_models": true,
     "comments": [{"target": "passage" or "cN", "quote": "...", "text": "...", "see_also": ["cM"]}]}
Adding the same file twice adds nothing.
"""
import argparse
import json
import sys
from pathlib import Path

from .. import human
from ..config import ROOT


def _read(file):
    try:
        return json.loads(Path(file).read_text(encoding="utf-8")), None
    except (OSError, ValueError) as e:
        return None, f"cannot read it as JSON: {e}"


def check(a):
    target = Path(a.path)
    files = sorted(target.rglob("*.json")) if target.is_dir() else [target]
    runs, bad = Path(a.runs) if a.runs else ROOT / "runs", 0
    for f in files:
        sub, err = _read(f)
        run = runs / f.parent.name
        errs = [err] if err else ([f"no run {run}"] if not (run / "page.json").exists() else human.problems(run, sub, f))
        for e in errs:
            print(f"{f}: {e}")
        bad += bool(errs)
    print(f"{len(files)} submission(s), {bad} with problems")
    sys.exit(1 if bad else 0)


def add(a):
    sub, err = _read(a.file)
    if err:
        sys.exit(f"{a.file}: {err}")
    if a.name:
        sub["name"] = a.name
    errs, ids = human.add(a.run, sub, a.file)
    if errs:
        sys.exit("\n".join(f"{a.file}: {e}" for e in errs))
    print(f"added {', '.join(ids)}" if ids else "already on the page; nothing added")


def template(a):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the output is meant to be saved as a file
    print(human.template(a.run, a.blind))


def register(sub):
    p = sub.add_parser("human", help="add, check or start a person's comments", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="act", required=True, metavar="<add|check|template>")
    q = s.add_parser("add", help="validate a submission and add it to a page")
    q.add_argument("run")
    q.add_argument("--file", required=True)
    q.add_argument("--name", help="the person's name, if not the one in the file")
    q.set_defaults(f=add)
    q = s.add_parser("check", help="validate submissions without writing; exit 1 on any problem")
    q.add_argument("path", help="a submission file, or a folder of them such as humans/")
    q.add_argument("--runs", help="folder of runs (default runs/)")
    q.set_defaults(f=check)
    q = s.add_parser("template", help="print a starter submission and the text to read")
    q.add_argument("run")
    q.add_argument("--blind", action="store_true", help="the passage alone, for a reader who has not seen the page")
    q.set_defaults(f=template)
