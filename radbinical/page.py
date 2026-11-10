"""The page: a passage, its comments, and how one reader sees them."""
import json
import re
import threading
from pathlib import Path

from .anchoring import locate, snap_to_sentences


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

    def save(self):
        with self.lock:
            (self.dir / "page.json").write_text(json.dumps(self.d, indent=1, ensure_ascii=False), encoding="utf-8")

    def add(self, author, layer, args):
        """Validate and record one annotation. Returns (ok, message for the model)."""
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
            d["counter"] += 1
            c["n"] = d["counter"]
            c["id"] = f"c{c['n']}"
            d["comments"].append(c)
            return True, f"Recorded as {c['id']}."
