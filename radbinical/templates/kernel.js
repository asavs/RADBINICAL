// The kernel: where on its text a comment is. Every layout of the page is built on these, and none
// of them touches the document, so they can be run and tested on their own.
//
// A node is the passage or a comment. A comment is on a node (its `target`) and may be on a span of
// that node's text; with no span it is on the whole text. The passage's text is shown as written; a
// comment's is shown as one run, its line breaks and repeated spaces closed up.

const shownText = c => c.text.replace(/\s+/g, ' ').trim();

// The span [start, end) of comment `c` in the shown text of the node it is on, or null when it is on
// the whole text. A comment on the passage stores its span. A comment on a comment quotes the
// words it means, copied from that comment, and its span is where they are found; `on` is the
// comment it is written on.
function spanOf(c, on) {
  if (c.target === 'passage') return [c.start, c.end];
  const q = (c.quote || '').replace(/\s+/g, ' ').trim();
  const i = q && on ? shownText(on).indexOf(q) : -1;
  return i < 0 ? null : [i, i + q.length];
}

// A text cut wherever a span starts or ends, and at any offset in `cuts`. `spans` is
// [{id, start, end}]. Returns the pieces in order, [{start, end, on, begins}]: `on` the ids of the
// spans that cover the piece, `begins` the ids of the spans that start at its first character.
// Spans may overlap, nest or coincide.
function pieces(text, spans, cuts = []) {
  const n = text.length, at = new Set([0, n, ...cuts]);
  spans = spans.map(s => ({ id: s.id, start: Math.max(0, Math.min(n, s.start)), end: Math.max(0, Math.min(n, s.end)) })).filter(s => s.end > s.start);
  for (const s of spans) { at.add(s.start); at.add(s.end) }
  const pts = [...at].filter(p => p >= 0 && p <= n).sort((a, b) => a - b), out = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const start = pts[i], end = pts[i + 1];
    out.push({ start, end, on: spans.filter(s => s.start <= start && s.end >= end).map(s => s.id), begins: spans.filter(s => s.start === start).map(s => s.id) });
  }
  return out;
}

// Boxes down one column, each wanting to start level with the words it is on. `items` is [{want}] in
// order down the page, `want` the height of its words. A box starts at its words, or as soon after
// the box above as leaves that box `least`, and runs to where the next one starts; the last runs to
// `end`, the foot of the text. No box is less than `least` high. Returns [{top, height}].
function place(items, least, gap = 0, end = Infinity) {
  const tops = [];
  let floor = 0;
  for (const it of items) {
    tops.push(Math.max(it.want, floor));
    floor = tops[tops.length - 1] + least + gap;
  }
  return tops.map((top, i) => ({ top, height: i < tops.length - 1 ? tops[i + 1] - top - gap : Math.max(least, end - top) }));
}

// Which side of its text a comment stands on: the side its words begin nearer to. `x` is where they
// begin, `lo` and `hi` the text's two edges. Returns 0 for the `lo` side and 1 for the `hi` side.
const nearer = (x, lo, hi) => (x - lo <= hi - x ? 0 : 1);

// Boxes whose words are too close together for each to have room, gathered into stacks. `items` is
// [{want}] in order down the page. A box that could not start at its words, because the box above
// needs `least` to show, joins that box as a stack; so every stack starts at the words of its first
// member. Returns the stacks in order, each a list of indexes into `items`.
function stacks(items, least, gap = 0) {
  const out = [];
  let floor = -Infinity;
  items.forEach((it, i) => {
    if (out.length && floor > it.want) return out[out.length - 1].push(i);
    out.push([i]);
    floor = it.want + least + gap;
  });
  return out;
}

if (typeof module !== 'undefined') module.exports = { shownText, spanOf, pieces, place, nearer, stacks };
