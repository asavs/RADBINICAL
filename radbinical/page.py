"""The page: a passage, its comments, and how one reader sees them.

A run lives in one folder. `page.json` is the page itself: the passage (with `id`, the passage
file's stem), the readers, `cast` (a short hash of the readers' model ids, see `cast_of`), `group`
(shared by repeated runs of one config; otherwise the folder name), the flags, the comments and
the log of every turn. A run may also carry an optional `lineage`.

Anything else a later step produces about a run goes beside it as its own JSON file,
`<run>/<name>.json` (`redactions.json`, `forecasts.json`, ...), never into `page.json`. Use
`read_side` / `write_side`, or `Page.side` / `Page.save_side`. A side file that called models may
carry a top-level `"usage"` list of usage dicts (as `ask` returns them); the table adds up their
`cost` into the run's cost.
"""
import hashlib
import json
import re
import threading
from pathlib import Path

from .anchoring import locate, snap_to_sentences
from .providers import canonical, split_model


def reader_entry(m):
    """A reader record from a config entry: a bare model id or a dict with model, name, protocol..."""
    if isinstance(m, str):
        m = {"model": m}
    name = m.get("name") or split_model(m["model"])[1].split("/")[-1]
    return {**{k: m[k] for k in ("protocol", "max_tokens", "brand") if k in m}, "model": m["model"], "name": name}


def is_human(reader):
    """Whether a reader record is a person (added by `human add`) rather than a model."""
    return bool(reader.get("human")) or str(reader.get("model", "")).startswith("human:")


def models_of(d):
    """The page's model readers, in page order: every reader but the people."""
    return [r for r in d["readers"] if not is_human(r)]


def labeller(d, signed=None):
    """How authors are named to a model reading the page: by name when signed (default: the
    page's `signed` flag), else "Reader A", "Reader B", ... in the order readers joined, people
    included, so a reader's letter never changes as others join."""
    if d["flags"].get("signed", True) if signed is None else signed:
        return lambda a: a
    pseudonyms = {r["name"]: f"Reader {chr(65 + i)}" for i, r in enumerate(d["readers"])}
    return lambda a: pseudonyms.get(a, "Reader")


def cast_of(readers):
    """Short stable id for a set of readers: a hash of their sorted canonical model ids, so the
    same models give the same cast however they are written or routed. People are not counted."""
    ids = sorted(canonical(r["model"] if isinstance(r, dict) else r) for r in readers
                 if not (isinstance(r, dict) and is_human(r)))
    return hashlib.sha1("\n".join(ids).encode("utf-8")).hexdigest()[:8]


def read_side(run_dir, name):
    """The side file `<run_dir>/<name>.json`, or None if it does not exist."""
    f = Path(run_dir) / f"{name}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def write_side(run_dir, name, obj):
    if name == "page":
        raise ValueError("page.json is the page itself, not a side file")
    (Path(run_dir) / f"{name}.json").write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def load_passage(path):
    raw = Path(path).read_text(encoding="utf-8")
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", raw) if p.strip()]
    return "\n\n".join(paras)


def children(page, cid):
    return [c for c in page["comments"] if c["target"] == cid]


def render_for_reader(page, visible, label, me):
    """Plain-text view of the page as one reader sees it."""
    p = page["passage"]
    out = ["=== THE PASSAGE ===", f"{p['title']}" + (f" ({p['source']})" if p.get("source") else ""), "", p["text"], ""]
    out.append(f"=== THE MARGINS ({len(visible)} comment{'s' if len(visible) != 1 else ''}) ===")
    if not visible:
        out.append("(empty)")
    vis_ids = {c["id"] for c in visible}

    def walk(c, depth):
        pad = "    " * depth
        who = label(c["author"]) + (" (you)" if c["author"] == me else "")
        where = "on the passage" if c["target"] == "passage" else f"on {c['target']}"
        if c.get("stale"):
            where += f" (its words were amended away in version {c['stale']})"
        q = f': "{c["quote"]}"' if c.get("quote") else ""
        out.append(f"{pad}[{c['id']}] {who}, {where}{q}")
        for line in c["text"].splitlines() or [""]:
            out.append(f"{pad}    {line}")
        if c.get("see_also"):
            out.append(f"{pad}    (see also: {', '.join(c['see_also'])})")
        out.append("")
        for k in children(page, c["id"]):
            if k["id"] in vis_ids:
                walk(k, depth + 1)

    tops = [c for c in visible if c["target"] == "passage"]
    for c in sorted(tops, key=lambda c: (c["start"], c["n"])):
        walk(c, 0)
    return "\n".join(out)


class Page:
    def __init__(self, data, out_dir):
        self.d, self.dir, self.lock = data, Path(out_dir), threading.Lock()

    @classmethod
    def load(cls, run_dir):
        return cls(json.loads((Path(run_dir) / "page.json").read_text(encoding="utf-8")), run_dir)

    def side(self, name):
        return read_side(self.dir, name)

    def save_side(self, name, obj):
        write_side(self.dir, name, obj)

    def save(self):
        with self.lock:
            (self.dir / "page.json").write_text(json.dumps(self.d, indent=1, ensure_ascii=False), encoding="utf-8")

    def add(self, author, layer, args, kind=None, meta=None):
        """Validate and record one annotation. Returns (ok, message for the model).

        `kind` marks a comment that is not a model's own reading ("plant", "human"); `meta` is a
        dict of notes about it. Both are stored on the comment and never shown to readers.
        """
        d, flags = self.d, self.d["flags"]
        target = str(args.get("target", "")).strip().strip("[]")
        text = str(args.get("text", "")).strip()
        quote = str(args.get("quote") or "").strip()
        if not text:
            return False, "Not recorded: the comment text is empty."
        with self.lock:
            by_id = {c["id"]: c for c in d["comments"]}
            c = {"author": author, "layer": layer, "text": text}
            if target.lower() == "passage":
                if not quote:
                    return False, "Not recorded: a comment on the passage needs `quote`, the exact words it attaches to."
                span = locate(d["passage"]["text"], quote)
                if not span:
                    return False, "Not recorded: that quote was not found in the passage. Copy the words exactly as they appear."
                if flags["anchor"] == "sentence":
                    span = snap_to_sentences(d["passage"]["text"], *span)
                c.update(target="passage", start=span[0], end=span[1], quote=d["passage"]["text"][span[0]:span[1]])
            elif target in by_id:
                parent = by_id[target]
                if parent["author"] == author and not flags["allow_self_reply"]:
                    return False, "Not recorded: replying to your own comment is switched off for this page."
                c.update(target=target)
                if quote:
                    span = locate(parent["text"], quote)
                    c["quote"] = parent["text"][span[0]:span[1]] if span else quote
            else:
                return False, f'Not recorded: no comment with id "{target}". Use "passage" or an id shown on the page.'
            refs = [str(r).strip("[] ") for r in (args.get("see_also") or [])] if flags["cross_refs"] else []
            refs = [r for r in refs if r in by_id]
            if refs:
                c["see_also"] = refs
            if kind:
                c["kind"] = kind
            if meta:
                c["meta"] = dict(meta)
            d["counter"] += 1
            c["n"] = d["counter"]
            c["id"] = f"c{c['n']}"
            d["comments"].append(c)
            return True, f"Recorded as {c['id']}."
