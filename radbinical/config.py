"""Paths, default switches, and loading keys from .env."""
import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parent          # runs/, docs/, passages/ and .env live here
TEMPLATES = PACKAGE / "templates"


DEFAULT_FLAGS = {
    "max_layers": 4,              # hard cap on rounds
    "stop_when_all_pass": True,   # end early once a whole round adds nothing
    "blind_first_layer": True,    # round 1: everyone glosses the bare text independently
    "sequential": False,          # later rounds: one at a time, each seeing the live page
    "signed": True,               # False: readers see each other as "Reader A", "Reader B"...
    "anchor": "span",             # "span" (any quoted run) or "sentence" (snapped to whole sentences)
    "cross_refs": True,           # allow see_also pointers between comments
    "allow_self_reply": True,
    "max_comments_per_turn": None,
    "max_tokens": 8000, 
    "temperature": None,
    "seed": 0,
    "forecast": False,            # before each round after the first, readers name the comments they expect to draw replies
}


def load_dotenv():
    """Read KEY=value lines from .env at the top of the repository. Variables already set win."""
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip("'\"")
        if k and v and k not in os.environ:
            os.environ[k] = v
