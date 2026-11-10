"""Finding a quoted span inside a text, tolerant of small copying differences."""
import re


_FOLD = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}


def fold(s):
    """Normalise for matching; returns (folded, map from folded index -> original index)."""
    out, idx, prev_space = [], [], False
    for i, ch in enumerate(s):
        ch = _FOLD.get(ch, ch)
        if ch.isspace():
            if prev_space:
                continue
            ch, prev_space = " ", True
        else:
            prev_space = False
        out.append(ch.lower())
        idx.append(i)
    return "".join(out), idx


def locate(haystack, quote):
    """Find quote in haystack tolerant of whitespace, case and curly quotes. -> (start, end) or None."""
    h, idx = fold(haystack)
    q = fold(quote.strip())[0].strip()
    for cand in (q, q.strip(" .\"'"), q.replace("...", "").replace("…", "").strip(" .\"'")):
        if len(cand) < 2:
            continue
        k = h.find(cand)
        if k >= 0:
            return idx[k], idx[k + len(cand) - 1] + 1
    return None


def snap_to_sentences(text, start, end):
    bounds = [0] + [m.end() for m in re.finditer(r"[.!?][\"')\]\u201d\u2019]*\s+", text)] + [len(text)]
    s = max(b for b in bounds if b <= start)
    e = min(b for b in bounds if b >= end)
    return s, len(text[:e].rstrip())
