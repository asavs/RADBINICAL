// The controls of a served page: writing a comment, asking models for a round or for a comment on
// chosen words, taking a comment off the page, and settings. The viewer calls live(V) once, with
// what it shares: V.D the page's record, V.reload(record) to show a newer one, V.byId(id),
// V.$ and V.esc. It returns what the viewer calls back: card(c), the actions under a comment in
// the reading view.
function live(V) {
  const D = V.D, L = D.live, $ = V.$, esc = V.esc;
  const PROVIDERS = { openrouter: 'OpenRouter', anthropic: 'Anthropic', openai: 'OpenAI', google: 'Google', xai: 'xAI', nous: 'Nous', nvidia: 'NVIDIA' };
  const MAKER = { anthropic: 'anthropic', openai: 'openai', google: 'google', 'x-ai': 'xai' }; // makers whose models go only to their own API

  // What this browser remembers: keys, the reader's name, the models last asked, the pages opened.
  const kept = (k, v) => {
    try {
      if (v === undefined) return JSON.parse(localStorage.getItem('radbinical.' + k));
      localStorage.setItem('radbinical.' + k, JSON.stringify(v));
    } catch (e) { return null }
  };
  const call = (path, body) => fetch(`/api/pages/${L.id}${path}`, body && { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    .then(async r => { const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || r.statusText); return j });
  const pages = (kept('pages') || []).filter(p => p.id !== L.id);
  kept('pages', [{ id: L.id, title: D.passage.title, at: Date.now() }, ...pages].slice(0, 200));

  document.head.insertAdjacentHTML('beforeend', `<style>
.lv-status { flex-basis: 100%; font-family: var(--small); font-size: 0.85rem; color: var(--ink-2); min-height: 1.3em }
.lv-status.busy { color: var(--warn) }
#lv-pop { position: absolute; z-index: 5; display: flex; background: var(--ink); border-radius: 0.4rem; padding: 0.15rem; box-shadow: 0 0.3rem 0.9rem rgb(0 0 0 / 0.3) }
#lv-pop[hidden] { display: none }
#lv-pop button { background: none; border: none; color: var(--sheet); font: 600 0.85rem var(--ui); padding: 0.35rem 0.7rem; border-radius: 0.3rem }
#lv-pop button:hover, #lv-pop button:focus-visible { background: color-mix(in srgb, var(--sheet) 22%, transparent) }
#lv-pop button + button { margin-left: 0.15rem }
#lv-dlg { width: min(32rem, calc(100% - 2rem)) }
#lv-dlg form { display: flex; flex-direction: column; gap: 0.8rem; font-family: var(--ui); font-size: 0.92rem }
#lv-dlg .on { font-family: var(--gloss); font-size: 1.02rem; border-left: 3px solid var(--mark); padding-left: 0.6rem; margin: 0 }
#lv-dlg label { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.82rem; color: var(--ink-2) }
#lv-dlg label.pick { flex-direction: row; align-items: baseline; gap: 0.5rem; font-size: 0.95rem; color: var(--ink) }
#lv-dlg label.pick small { color: var(--ink-2); overflow-wrap: anywhere }
#lv-dlg input:not([type=checkbox]), #lv-dlg textarea { font: inherit; font-size: 1rem; color: var(--ink); background: var(--paper); border: 1px solid var(--rule); border-radius: 0.25rem; padding: 0.4rem 0.5rem; width: 100% }
#lv-dlg textarea { font-family: var(--gloss); font-size: 1.08rem; line-height: 1.45; resize: vertical }
#lv-dlg input[type=checkbox] { accent-color: var(--ink) }
#lv-dlg fieldset { border: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.35rem }
#lv-dlg legend { font-family: var(--small); font-weight: 700; letter-spacing: 0.05em; color: var(--ink-2); padding: 0; margin-bottom: 0.3rem }
#lv-dlg .foot { display: flex; align-items: center; gap: 0.9rem; flex-wrap: wrap }
#lv-dlg .go { background: var(--ink); color: var(--sheet); border: none; border-radius: 999px; padding: 0.4rem 1.1rem; font-weight: 600 }
#lv-dlg .go:disabled { opacity: 0.5 }
#lv-dlg .err { color: var(--a0) }
#lv-dlg .note { color: var(--ink-2); font-size: 0.85rem; margin: 0 }
#lv-dlg .link { background: none; border: none; padding: 0; text-decoration: underline; color: inherit }
.lv-acts { display: flex; gap: 0.9rem; font-family: var(--small); font-size: 0.85rem }
.lv-acts button { background: none; border: none; padding: 0; color: var(--ink-2); text-decoration: underline 1px var(--rule); text-underline-offset: 3px }
.lv-acts button:hover { color: var(--ink) }
#lv-toast { position: fixed; left: 50%; bottom: 1.2rem; transform: translateX(-50%); z-index: 6; max-width: min(40rem, calc(100% - 2rem)); background: var(--ink); color: var(--sheet); padding: 0.55rem 0.9rem; border-radius: 0.4rem; font-size: 0.88rem; display: flex; flex-direction: column; gap: 0.3rem; box-shadow: 0 0.3rem 0.9rem rgb(0 0 0 / 0.3) }
#lv-toast:empty { display: none }
#lv-toast button { background: none; border: none; color: inherit; text-decoration: underline; padding: 0 0 0 0.6rem }
@media print { .lv-status, #lv-pop, #lv-toast { display: none } }
html.printing .lv-status, html.printing #lv-pop, html.printing #lv-toast { display: none }
</style>`);
  document.querySelector('.ctl').insertAdjacentHTML('beforeend', '<button id="lv-ask">Ask models</button><button id="lv-set">Settings</button><a href="/">Library</a>');
  document.querySelector('.bar').insertAdjacentHTML('beforeend', '<div class="lv-status" id="lv-status" aria-live="polite"></div>');
  document.body.insertAdjacentHTML('beforeend', `<div id="lv-pop" hidden><button data-do="add">Add comment</button><button data-do="ask">Request comment</button></div>
<dialog class="sheet" id="lv-dlg" aria-labelledby="lv-title"><div class="sheet-head"><span class="sheet-title" id="lv-title"></span><button class="sheet-close" id="lv-close">Close</button></div><div class="sheet-body" id="lv-body"></div></dialog>
<div id="lv-toast" role="status"></div>`);
  const pop = $('lv-pop'), dlg = $('lv-dlg'), toastEl = $('lv-toast');

  // Notices: a line at the foot of the window, gone after a while; `undo` adds a button to it.
  function toast(text, undo) {
    const line = document.createElement('div');
    line.textContent = text;
    if (undo) { const b = document.createElement('button'); b.textContent = 'Undo'; b.onclick = () => { line.remove(); undo() }; line.append(b) }
    toastEl.append(line);
    setTimeout(() => line.remove(), undo ? 12000 : 9000);
  }

  // Where the selection is, in the text it was made in: {target, span, quote, rect}, or null when
  // it is not within the passage or within one comment in the margins. What is shown differs from
  // the text by what the viewer leaves out (the break between paragraphs, the marks of emphasis)
  // and adds (comment numbers), so each shown character is matched to its place in the text.
  function selected() {
    const sel = getSelection();
    if (!sel.rangeCount || sel.isCollapsed) return null;
    const r = sel.getRangeAt(0), top = r.commonAncestorContainer, el = top.nodeType === 1 ? top : top.parentElement;
    const tx = el.closest('#body .tx'), root = tx || el.closest('#passage');
    if (!root) return null;
    const target = tx ? tx.closest('.c').id : 'passage';
    const text = tx ? shownText(V.byId(target)) : D.passage.text;
    const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: n => n.parentElement.closest('sup.m') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
    let seen = '', a = -1, b = -1;
    for (let n; (n = walk.nextNode());) {
      if (r.intersectsNode(n)) {
        const s = n === r.startContainer ? r.startOffset : 0, e = n === r.endContainer ? r.endOffset : n.length;
        if (e > s) { if (a < 0) a = seen.length + s; b = seen.length + e }
      }
      seen += n.data;
    }
    if (a < 0) return null;
    const at = [];
    for (let i = 0, j = 0; j < seen.length; j++) { while (i < text.length && text[i] !== seen[j]) i++; at.push(i++) }
    let s = at[a], e = at[b - 1] + 1;
    if (!(e <= text.length)) return null;
    while (s < e && /\s/.test(text[s])) s++;
    while (e > s && /\s/.test(text[e - 1])) e--;
    return e > s ? { target, span: [s, e], quote: text.slice(s, e), rect: r.getBoundingClientRect() } : null;
  }

  // The two choices offered on selected words.
  let chosen = null;
  function offer() {
    const w = selected();
    if (!w || dlg.open || V.sheet.open) { pop.hidden = true; return }
    chosen = w;
    pop.hidden = false;
    const x = Math.max(8, Math.min(innerWidth - pop.offsetWidth - 8, w.rect.left + w.rect.width / 2 - pop.offsetWidth / 2));
    pop.style.left = x + scrollX + 'px';
    pop.style.top = w.rect.bottom + scrollY + 8 + 'px';
  }
  let wait = 0;
  document.addEventListener('selectionchange', () => { clearTimeout(wait); wait = setTimeout(offer, 250) });
  pop.addEventListener('mousedown', e => e.preventDefault()); // keep the selection while choosing
  pop.addEventListener('click', e => {
    const b = e.target.closest('[data-do]'); if (!b || !chosen) return;
    const w = { target: chosen.target, span: chosen.span, quote: chosen.quote };
    getSelection().removeAllRanges(); pop.hidden = true;
    b.dataset.do === 'add' ? addForm(w) : askForm(w);
  });

  // The dialog all three forms share.
  function show(title, html, submit) {
    $('lv-title').textContent = title;
    $('lv-body').innerHTML = `<form>${html}</form>`;
    const form = $('lv-body').firstElementChild, err = form.querySelector('.err'), go = form.querySelector('.go');
    form.addEventListener('submit', async e => {
      e.preventDefault();
      if (err) err.textContent = '';
      if (go) go.disabled = true;
      try { if (await submit(form) !== false) dlg.close() } catch (x) { if (err) err.textContent = x.message }
      if (go) go.disabled = false;
    });
    if (!dlg.open) dlg.showModal();
    const first = form.querySelector('textarea, input:not([type=checkbox])');
    if (first) first.focus();
    return form;
  }
  $('lv-close').addEventListener('click', () => dlg.close());
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close() });
  const short = (q, n = 40) => { const w = q.trim().split(/\s+/); return w.length > n ? w.slice(0, n).join(' ') + '…' : q.trim() };
  const onHTML = w => {
    if (!w) return '';
    const c = w.target !== 'passage' && V.byId(w.target);
    const whose = c ? `comment ${w.target.slice(1)}, by ${esc(c.author)}` : 'the passage';
    return `<p class="on">${w.quote ? `“${esc(short(w.quote))}”<br><small>in ${whose}</small>` : `<small>On ${whose}</small><br>${esc(short(shownText(c), 30))}`}</p>`;
  };

  function addForm(w) {
    show('Add a comment', `${onHTML(w)}
      <label>Your comment<textarea name="text" rows="6" required></textarea></label>
      <label>Your name, as it will stand on the page<input name="name" required maxlength="60" value="${esc(kept('name') || '')}"></label>
      <div class="foot"><button class="go">Add comment</button><span class="err"></span></div>`, async f => {
      kept('name', f.name.value.trim());
      await call('/comment', { ...w, name: f.name.value, text: f.text.value });
      tick();
    });
  }

  // The id a model is asked by. A maker's model goes only to its maker's API, which needs that
  // maker's key; a reader who has only an OpenRouter key gets it sent through OpenRouter, and the
  // page records that in the reader's model id.
  function routed(model) {
    const keys = kept('keys') || {}, [vendor, rest] = model.split('/');
    const maker = !model.includes(':') && rest && MAKER[vendor];
    return maker && !keys[maker] && keys.openrouter && !L.env_keys ? 'openrouter:' + model : model;
  }
  function askForm(w) {
    const here = D.readers.filter(r => !r.human && !r.model.startsWith('human:'));
    const names = new Set(here.map(r => r.name));
    const list = [...here, ...L.models.filter(m => !names.has(m.name))], last = new Set(kept('asked') || []);
    const keys = kept('keys') || {}, none = !L.env_keys && !Object.values(keys).some(Boolean);
    const form = show(w ? 'Request a comment' : 'Ask models for a round', `${onHTML(w)}
      <p class="note">${w ? 'Each model you choose is asked for one comment on these words.' : 'Each model you choose reads the page as it stands and comments where it likes.'} Those asked together do not see each other's answers.</p>
      <fieldset><legend>Models</legend>${list.map((m, i) => `<label class="pick"><input type="checkbox" name="m" value="${i}"${last.has(m.name) ? ' checked' : ''}><span>${esc(m.name)}</span><small>${esc(m.model)}</small></label>`).join('')}</fieldset>
      <label>Another model, by its id<input name="other" placeholder="vendor/name" maxlength="120" autocomplete="off"></label>
      ${none ? '<p class="note">You have not given a key yet, so no model can be reached. <button type="button" class="link" id="lv-tokeys">Add one in Settings</button></p>' : ''}
      <div class="foot"><button class="go">${w ? 'Request' : 'Ask'}</button><span class="err"></span></div>`, async f => {
      const picked = [...f.querySelectorAll('[name=m]:checked')].map(b => list[+b.value]);
      kept('asked', picked.map(m => m.name));
      const models = picked.map(m => here.includes(m) ? { model: m.model, name: m.name } : { model: routed(m.model), name: m.name });
      if (f.other.value.trim()) models.push({ model: routed(f.other.value.trim()) });
      if (!models.length) throw new Error('Choose at least one model.');
      await call('/ask', { models, keys: kept('keys') || {}, ...(w ? { on: w } : {}) });
      tick();
    });
    const to = form.querySelector('#lv-tokeys'); if (to) to.onclick = settingsForm;
  }

  function settingsForm() {
    const keys = kept('keys') || {}, order = Object.keys(PROVIDERS).filter(p => L.providers.includes(p));
    show('Settings', `
      <label>Your name, as it will stand on the page<input name="name" maxlength="60" value="${esc(kept('name') || '')}"></label>
      <fieldset><legend>This page</legend>
        <label class="pick"><input type="checkbox" name="signed"${D.flags.signed ? ' checked' : ''}><span>Models are told who wrote each comment</span></label>
        <p class="note">When this is off they see “Reader A”, “Reader B” and so on.</p></fieldset>
      <fieldset><legend>Your keys</legend>
        <p class="note">Kept in this browser. They are sent with each request you make to a model and are not stored by the server.${L.env_keys ? ' This server also has keys of its own, used for any provider you leave empty.' : ''} An OpenRouter key alone reaches every model listed.</p>
        ${order.map(p => `<label>${PROVIDERS[p]}<input type="password" name="key-${p}" value="${esc(keys[p] || '')}" autocomplete="off" spellcheck="false"></label>`).join('')}</fieldset>
      <div class="foot"><button class="go">Save</button><span class="err"></span></div>`, async f => {
      kept('name', f.name.value.trim());
      kept('keys', Object.fromEntries(order.map(p => [p, f['key-' + p].value.trim()]).filter(([, k]) => k)));
      if (f.signed.checked !== D.flags.signed) { await call('/flags', { signed: f.signed.checked }); tick() }
    });
  }
  $('lv-ask').addEventListener('click', () => askForm(null));
  $('lv-set').addEventListener('click', settingsForm);

  // Under each comment in the reading view.
  const card = c => `<div class="lv-acts"><button data-lv="add" data-id="${c.id}">Reply</button><button data-lv="ask" data-id="${c.id}">Ask a model</button><button data-lv="hide" data-id="${c.id}">Remove</button></div>`;
  document.addEventListener('click', async e => {
    if (V.sheet.open) pop.hidden = true;
    const b = e.target.closest('[data-lv]'); if (!b) return;
    const id = b.dataset.id;
    if (b.dataset.lv === 'add') return addForm({ target: id });
    if (b.dataset.lv === 'ask') return askForm({ target: id });
    V.sheet.close();
    try {
      await call('/hide', { id, hidden: true });
      toast(`Comment ${id.slice(1)} was taken off the page. It stays in the record.`, () => call('/hide', { id, hidden: false }).then(tick));
    } catch (x) { toast(x.message) }
    tick();
  });

  // Keeping up with the page: who is reading now, and whatever has been written since.
  let v = null, pending = [], cost = 0, logged = D.log.length, timer = 0;
  function status() {
    const who = [...new Set(pending.map(p => p.reader))], el = $('lv-status');
    const spent = cost > 0 ? ` · about $${cost < 0.1 ? cost.toFixed(3) : cost.toFixed(2)} so far` : '';
    el.classList.toggle('busy', who.length > 0);
    if (who.length) el.textContent = (who.length > 1 ? who.slice(0, -1).join(', ') + ' and ' + who[who.length - 1] + ' are' : who[0] + ' is') + ' reading…' + spent;
    else if (!D.comments.length) el.textContent = 'Select words to comment on them or to ask a model about them, or ask models for a round.';
    else el.textContent = spent.slice(3);
  }
  async function tick() {
    clearTimeout(timer);
    try {
      const s = await call('?v=' + encodeURIComponent(v || ''));
      if (!s.same) {
        v = s.v; pending = s.pending; cost = s.cost;
        for (const e of s.page.log.slice(logged)) {
          if (e.error) toast(`${e.reader} could not answer. ` + (/HTTP 40[13]\b|\bkey\b|_KEY\b/.test(e.error) ? 'Its provider did not accept a key from you; keys are in Settings. ' : '') + `(${e.error})`);
          else if (!e.comments && e.via !== 'human') toast(`${e.reader} wrote no comment.` + (e.closing ? ` It said: “${short(e.closing, 30)}”` : ''));
        }
        logged = s.page.log.length;
        pop.hidden = true;
        V.reload({ ...s.page, live: L });
        status();
      }
    } catch (e) { /* the server may be away for a moment; try again */ }
    timer = setTimeout(tick, document.hidden ? 15000 : pending.length ? 1500 : 6000);
  }
  status();
  tick();
  return { card };
}
