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

// Boxes down one column, each wanting to start level with the words it is on. `items` is
// [{want, height}] in order down the page: `want` the height of its words, `height` what the box
// needs to show everything. A box starts at its words, or as soon after the box above as leaves
// that box `least` to show, and is cut where the next one starts. The last is cut at `end`, the
// foot of the text, when that is given, though never to less than `least`.
// Returns [{top, height, cut}].
function place(items, least, gap = 0, end = Infinity) {
  const out = [];
  let floor = 0;
  for (const it of items) {
    const top = Math.max(it.want, floor);
    out.push({ top, height: it.height, cut: false });
    floor = top + least + gap;
  }
  for (let i = 0; i < out.length; i++) {
    const room = i < out.length - 1 ? out[i + 1].top - out[i].top - gap : Math.max(least, end - out[i].top);
    if (out[i].height > room) { out[i].height = room; out[i].cut = true }
  }
  return out;
}

// Which of several columns each box goes to, so that as few as possible start below their words:
// each, in order, to the column where it can start highest, the earlier column on a tie.
// `ends` has one entry per column. Returns the column of each item.
function share(items, columns, least, gap = 0) {
  const floor = Array(columns).fill(0);
  return items.map(it => {
    let best = 0;
    for (let k = 1; k < columns; k++) if (Math.max(it.want, floor[k]) < Math.max(it.want, floor[best])) best = k;
    floor[best] = Math.max(it.want, floor[best]) + least + gap;
    return best;
  });
}

if (typeof module !== 'undefined') module.exports = { shownText, spanOf, pieces, place, share };
