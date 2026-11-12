// The kernel: where on its text a comment is. Every layout of the page is built on these, and none
// of them touches the document, so they can be run and tested on their own.
//
// A node is the passage or a comment. A comment is on a node (its `target`) and may be on a span of
// that node's text; with no span it is on the whole text. The passage's text is shown as written; a
// comment's is shown as one run, its line breaks and repeated spaces closed up.

const shownText = c => c.text.replace(/\s+/g, ' ').trim();

// The span [start, end) of comment `c` in the shown text of the node it is on, or null when it is on
// the whole text. A comment on the passage stores its span, and a comment on a comment may. One
// that does not quotes the words it means, copied from that comment, and its span is where they
// are first found; `on` is the comment it is written on.
function spanOf(c, on) {
  if (c.target === 'passage' || (c.start != null && c.end != null)) return [c.start, c.end];
  const q = (c.quote || '').replace(/\s+/g, ' ').trim();
  const i = q && on ? shownText(on).indexOf(q) : -1;
  return i < 0 ? null : [i, i + q.length];
}

// A text cut wherever a span starts or ends, and at any offset in `cuts`. `spans` is
// [{id, start, end}]. Returns the pieces in order, [{start, end, on, begins, ends}]: `on` the ids of
// the spans that cover the piece, `begins` the ids of the spans that start at its first character,
// `ends` the ids of those that end with its last.
// Spans may overlap, nest or coincide.
function pieces(text, spans, cuts = []) {
  const n = text.length, at = new Set([0, n, ...cuts]);
  spans = spans.map(s => ({ id: s.id, start: Math.max(0, Math.min(n, s.start)), end: Math.max(0, Math.min(n, s.end)) })).filter(s => s.end > s.start);
  for (const s of spans) { at.add(s.start); at.add(s.end) }
  const pts = [...at].filter(p => p >= 0 && p <= n).sort((a, b) => a - b), out = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const start = pts[i], end = pts[i + 1];
    out.push({ start, end, on: spans.filter(s => s.start <= start && s.end >= end).map(s => s.id), begins: spans.filter(s => s.start === start).map(s => s.id), ends: spans.filter(s => s.end === end).map(s => s.id) });
  }
  return out;
}

// Which edge of its text a comment is written at: the one its words end nearest. (`x`, `y`) is where
// they end, measured from the text's top left corner, and `w` and `h` are the text's width and
// height. Returns 'left', 'right', 'above' or 'below'; a side wins a tie with above or below.
function edge(x, y, w, h) {
  const d = { left: x, right: w - x, above: y, below: h - y };
  return Object.keys(d).reduce((a, b) => (d[b] < d[a] ? b : a));
}

// Notes down one margin, each wanting to start level with where its words end. `items` is
// [{want, h}] in order down the page: `want` the height of those words and `h` the note's own
// height. Every note is whole and keeps its place in the order. One with room starts at its words.
//
// The stretch of margin from a note's words down to the next note's words is the room it is
// entitled to. When the note above runs into it, the one with room to spare gives way:
// - it starts lower, right under the note above, if it can do that and still end before the next
//   note's words (the last note always can: the margin below it is open). It gives way by up to
//   `give` on its own; of any more than that it takes half, and the notes above it that touch move
//   up by the other half, as far as the margin above them is free;
// - if it cannot, those notes above move up instead, into whatever margin is free above them, so
//   that it can start at its words;
// - and whatever the free margin above does not cover, it makes up by starting lower.
// The margin begins at `top`: no note starts above that. Returns each note's top.
function stack(items, gap = 0, give = Infinity, top = -Infinity) {
  const tops = [];
  let run = 0, free = top; // the first of the notes now touching, and the highest that one may start
  items.forEach((it, i) => {
    const foot = i ? tops[i - 1] + items[i - 1].h + gap : top; // the highest this note can start, the notes above staying put
    if (it.want >= foot) { tops.push(it.want); run = i; free = foot; return }
    const need = foot - it.want, next = items[i + 1], spare = !next || foot + it.h + gap <= next.want;
    const up = i ? Math.min(Math.max(0, tops[run] - free), spare ? Math.max(0, need - give) / 2 : need) : 0;
    for (let k = run; k < i; k++) tops[k] -= up;
    tops.push(foot - up);
  });
  return tops;
}

if (typeof module !== 'undefined') module.exports = { shownText, spanOf, pieces, edge, stack };
