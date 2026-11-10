# Plan

## The question

In domains where nobody can check the answer, humans do not verify conclusions. They build
institutions that make reasoning inspectable and contestable: precedent, peer review, recorded
dissent, appeal. The Talmud keeps minority opinions because a later court may need them.

So the thing to climb is the health of the process, not the correctness of the output. Parts of
that are checkable even when the subject is not:

| Handle | Question | Measured by |
|---|---|---|
| Error correction | When a comment contains a mistake, does someone catch it, and how fast? | Planted error (2A) |
| Faithfulness | When a model summarises a dispute, does the summary match the page? | Redactor (2B) |
| Diversity retention | Do distinct readings survive the rounds or collapse into one? | Readings (2C) |
| Calibration | Is "from memory, check this" wrong more often than an unhedged claim? | Calibration (2A) |

## What is not yet known

- Three runs is not evidence of basins. Nobody has run the same cast twice on the same text, so
  nothing separates a reading from noise.
- Convergence may be shallow. Models trained on the same literature all know the standard
  objection to Mill's production/distribution split; agreement there may show shared training, not
  shared reasoning.
- Nothing measures whether later rounds improve on earlier ones.
- The dense sheet trades reading comfort for the look. Watch whether readers use the sheet or go
  straight to the threads.

## Phases

Each phase lands on the `roadmap` branch with the tests passing before the next begins. Work
inside a phase runs in parallel, one git worktree per track, and each track owns its files.

### Phase 1: foundation

One track. Everything later depends on it.

- **Row-per-comment table.** `python -m radbinical table` flattens every run into
  `data/comments.jsonl` (one row per comment: run, passage, cast, group, model, reader, round, id,
  parent, root, depth, start, end, quote, text, see_also, kind) and `data/runs.jsonl` (one row per
  run: passage, cast, group, flags, rounds, comment count, cost). `radbinical/table.py` exposes
  `rows()` and `runs()` for every analysis to read. A reply inherits its root's passage span.
  `page.json` stays the record each run writes; the table is rebuilt from the runs.
- **Identity.** Each run records `passage.id` (the passage file's stem), `cast` (a short hash of
  the sorted model ids) and `group` (shared by repeats of one config). The three existing runs are
  rewritten to carry them.
- **Repeated runs.** `run config.json --repeat 3` writes `<name>-a`, `-b`, `-c` with one `group`
  and different seeds.
- **One-shot calls.** `radbinical/ask.py`: `ask(model, system, user) -> (text, usage)` through the
  same provider prefixes as readers, with a deterministic `mock:` answer. The judge, the redactor,
  rulings and forecasts all use it.
- **Commands as modules.** `cli.py` discovers `radbinical/commands/*.py`, each with
  `register(sub)`. A new feature adds a file and edits no shared one.
- **Comment kinds and hidden notes.** A comment may carry `kind` (`"plant"`, `"human"`; absent for
  a model's own) and a `meta` dict. Neither is shown to readers.
- **Side files.** Anything beyond the page itself goes in the run's folder as its own JSON file
  (`redactions.json`, `forecasts.json`, …), never into `page.json`.
- **Windows.** Every `read_text`/`write_text` names `encoding="utf-8"`; the test suite passes on
  Windows and Linux.

### Phase 2: instruments

Six tracks in parallel.

**2A. Planted error and calibration** — `commands/plant.py`, `commands/judge.py`, `radbinical/judge.py`
- `plant runs/<dir> --as <reader> --round k --target … --quote … --text … --truth …` inserts a
  comment marked `kind: "plant"` under an existing reader's name, with the nature of the slip in
  `meta`. Two sorts: a subtle factual slip or bad argument, and a sound but unfashionable reading.
- `judge plants runs/<dir>`: for each plant, a judge model reads its replies and records whether
  it was caught (or, for the sound reading, dismissed), by whom, and in which round. Writes
  `plants.json`.
- `judge claims runs/<dir>`: extracts checkable factual claims from comments, marks each hedged or
  not ("from memory", "check this"), and has a judge with the claim alone rate it right, wrong or
  unsure. Writes `claims.json`; the report is error rate hedged against unhedged.

**2B. The redactor** — `commands/redact.py`
- `redact runs/<dir> --models a,b,c`: each model compiles the page into what was disputed, what
  was settled and what stands unresolved, deciding nothing, citing comment ids for every item.
  Writes `redactions.json`.
- Checks that need no judge: every cited id exists; every quotation is found in the comment it
  cites. Then a judge rates each item against the comments it cites: supported, distorted or
  unsupported.
- `redact compare`: overlap between different models' redactions of one page, by cited ids.

**2C. Readings, the reply graph and round-over-round measures** — `commands/readings.py`, `commands/graph.py`, `commands/rounds_report.py`, `radbinical/embed.py`
- Embed every gloss; cluster glosses on overlapping spans across runs. A cluster is a reading.
  For each: which models produce it, in how many runs of a group, whether it is cited, challenged
  or withdrawn. Writes `data/readings.jsonl`.
- Noise floor: within a group of repeated runs, the share of readings that recur. This is the
  honest version of "basins".
- Reply graph over replies and `see_also`: in-degree, depth, and the comments many others build
  on. Writes `data/graph.jsonl`.
- Per round: new readings introduced, readings still alive (diversity retention), share of
  comments that reply rather than gloss afresh, share that engage a layer older than the previous
  one. For a reader who joins late, the share of its comments that engage existing layers.

**2D. Forecasts and case law** — `commands/caselaw.py`, `radbinical/forecast.py`, the round loop
- Flag `forecast` (default false): before each round after the first, each reader names the
  comments it expects to draw replies. Scored against what happens. Writes `forecasts.json`.
- `caselaw runs/<dir> --cases cases/<file>.json`: each model rules on each hypothetical twice,
  with the page and with the bare passage, citing comments as precedent when it has them. Writes
  `rulings.json`; the report is agreement between models with the page against without.

**2E. Lineages and amendment** — `commands/fork.py`, `commands/amend.py`
- `fork runs/<dir> --into n`: n isolated copies of a page, each extended on its own seed, sharing
  a `lineage`. With 2C this shows whether schools drift apart.
- `amend`: readers draft a short position statement, annotate it, then propose amendments as
  exact replacements of a quoted span. Each amendment is voted on; those reaching the threshold
  are applied, and the page carries every version of its text with the votes.

**2F. The site, humans and the workflow** — `templates/`, `site.py`, `commands/human.py`, `.github/workflows/`
- The Run workflow takes `mode` (`run` or `extend`), `rounds`, `models` and `repeat`. Each page
  gets an "Another round" link to that workflow; only the repository owner can start it.
- Humans are readers in the same format. `human add runs/<dir> --name … --file …` validates a
  submission (same anchoring rules) and adds its comments as `kind: "human"`. Submissions arrive as
  pull requests adding `humans/<run>/<name>.json`; the test workflow validates them. A submission
  marked `blind: true` is recorded as round 1, and can only be collected from someone who has not
  yet seen the models' comments.
- The viewer marks planted and human comments, and shows a run's side files when they exist
  (redactions, plants, forecasts).
- A print stylesheet: one poster-sized sheet per passage.

### Phase 3: integration

Merge the six tracks, run the whole suite, run every command end to end on mock readers, rewrite
the README to cover all of it.

### Phase 4: experiments

Real models, through OpenRouter. Spending cap for the phase: 15 USD, tracked from the usage each
call reports.

1. **Noise floor.** One cast, three times, on Mill.
2. **Obscure passage.** A public-domain passage with no commentary tradition, same cast, three
   times. Compare convergence with Mill.
3. **Accumulation.** Add a new model to a finished page; measure whether it engages the existing
   layers or glosses the text afresh. Repeat with authors hidden.
4. **Planted error.** One slip and one unfashionable-but-sound reading on a finished page, two
   more rounds, judged.
5. **Redactor.** Three models redact the same page; faithfulness and overlap.
6. **Forecasts and case law** on one page each.
7. **Schools.** One page forked into three lineages, two rounds each.

Results go in `FINDINGS.md`, with every number traceable to a file under `data/` or `runs/`.

### Phase 5: needs a person

- A blind human layer. It can be collected once per passage, before the person sees the page.
- A public "another round" button. Strangers would spend the owner's credits, so it needs a small
  server with a budget.
- Printing a sheet.
- Each new model release inherits the pages and adds a layer.
