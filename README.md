# Radbinical

Several language models read the same passage and write comments in its margins. Then they read
each other's comments and write on those, round after round, until nobody has more to add or the
round limit is reached. Nothing is scored.

Pages so far: https://asavs.github.io/RADBINICAL/

Why the instruments below exist, and what they are meant to show, is in [PLAN.md](PLAN.md).

## Run it

    python3 -m radbinical run config.json

This writes `runs/<name>/page.json`, the full record, and `runs/<name>/page.html`, a page you can
open in a browser. Python 3.10 or later; no packages needed unless you call Anthropic directly
(`pip install anthropic`).

    python3 -m radbinical run config.mock.json                       # no keys; placeholder comments
    python3 -m radbinical run config.json --out runs/mill-03         # choose the folder
    python3 -m radbinical extend runs/<name> -n 2                    # two more rounds
    python3 -m radbinical extend runs/<name> -n 1 --models x-ai/grok-4.7   # another reader joins
    python3 -m radbinical extend runs/<name> -n 1 --models qwen/qwen3.8-27b --only-new --max-tokens 40000
    python3 -m radbinical extend runs/<name> -n 2 --sit-out "Kimi K3"      # Kimi skips these rounds
    python3 -m radbinical render runs/<name>                         # rebuild page.html
    python3 -m radbinical site                                       # rebuild docs/ for the website

Every command explains itself with `-h`.

## Readers and keys

Each entry under `models` in the config is one reader. A prefix sends it to that provider; a bare
OpenRouter-style id (`vendor/model`) goes to its maker when the maker's key is set, and otherwise
through a shared provider: OpenRouter if its key is set, else Nous.

| Reader written as | Goes to | Key |
|---|---|---|
| `qwen/qwen3.8-27b` | OpenRouter, or Nous | `OPENROUTER_API_KEY`, `NOUS_API_KEY` |
| `anthropic/claude-opus-5.5` | Anthropic if its key is set, else as above | `ANTHROPIC_API_KEY` |
| `openai:gpt-6.1-sol` | OpenAI | `OPENAI_API_KEY` |
| `anthropic:claude-opus-5-5` | Anthropic | `ANTHROPIC_API_KEY` |
| `google:gemini-4-argon` | Google | `GEMINI_API_KEY` |
| `nvidia:nvidia/nemotron-3-ultra-550b-a55b` | NVIDIA | `NVIDIA_API_KEY` |
| `openrouter:nousresearch/hermes-4-405b` | OpenRouter, always | `OPENROUTER_API_KEY` |
| `nous:nousresearch/hermes-4-405b` | Nous, always | `NOUS_API_KEY` |
| `mock:anything` | No call; placeholder comments | none |

Bare ids are sent to their maker only for OpenAI, Anthropic, Google and NVIDIA. Ids with a variant
suffix such as `:free`, and OpenAI's open-weight `gpt-oss` models, always go through the shared
provider. A prefixed reader whose maker's key is missing goes through a shared provider when one
has a key and the model has an OpenRouter id. Each turn records the provider it went through as `via` in the page's log. The rules
live in `radbinical/providers/__init__.py`.

On your machine, copy `.env.example` to `.env` and fill in the keys you use; `.env` is ignored by
git, and a key already set in your shell wins. On GitHub, add them under Settings → Secrets and
variables → Actions with the same names.

A reader whose model can't call tools can be given `"protocol": "text"`; it then writes its
comments as tagged blocks in plain text. `"max_tokens"` can also be set per reader, and `"name"`
sets how it appears on the page.

Each reader is shown with its maker's logo and brand colour, worked out from the model id. The
table is `radbinical/brands.json`; the logos are linked from the lobe-icons set, not stored here.
A reader whose maker isn't in the table gets a plain coloured dot. To set the maker by hand, add
`"brand": "nousresearch"` (any key from the table) to the reader.

## Your own passage

Put the text in `passages/` as plain text with a blank line between paragraphs, and set
`passage.file`, `passage.title` and `passage.source` in the config. The file's name without
`.txt` is the passage's id; runs of one passage are compared by it.

## Repeated runs

    python3 -m radbinical run config.json --repeat 3 --out runs/mill-cast1

writes `runs/mill-cast1-a`, `-b` and `-c`. They share a `group` (`mill-cast1`) and take seeds
`seed`, `seed+1`, `seed+2`. Every page also records `cast`, a short hash of its models, so runs of
the same models can be found however the models were written. The website lists the repeats of
one config as one entry.

## The table

    python3 -m radbinical table

flattens every run into two files that every analysis reads:

| File | One row per | Holds |
|---|---|---|
| `data/comments.jsonl` | comment | run, passage, cast, group, lineage, model, reader, round, id, parent, root, depth, start, end, quote, text, see_also, kind, stale, inherited |
| `data/runs.jsonl` | run | passage, cast, group, lineage, readers, flags, rounds, comments, cost, cost_estimated, started |

A reply's start and end are its root's span on the passage. `kind` is `"plant"` or `"human"` for
comments that are not a model's own, and empty otherwise. `stale` is the version of an amended
text that lost a comment's quoted words. `inherited` marks the comments a fork copied from its
source. Each reader in a run's row carries `joined`, the round it entered the page: a model
reader's first turn in the log, whether or not it commented, and a person's first comment. `cost`
adds up the cost of every call, on the page and in its side files, and `cost_estimated` is the
part of it estimated from tokens (see Cost below). The table is rebuilt from `runs/` each time;
`page.json` stays the record.

## Cost

OpenRouter and Nous report what each call cost. Anthropic, OpenAI, Google and NVIDIA report
tokens only, so a call to one of them is priced from `radbinical/prices.json`, a snapshot of
OpenRouter's public price list, and its usage is marked `cost_estimated`. A model the snapshot
does not list gets no cost. The table prices logged turns that carry tokens but no cost the same
way when it reads them; side files are taken as stored.

    python3 -m radbinical prices                       # refresh prices.json from OpenRouter; no key
    python3 -m radbinical spend                        # reported, estimated and sum, per run and in total
    python3 -m radbinical spend --since 2026-11-10     # runs started at or after this

`spend` counts the log and every side file's usage; its last line is `total <number> USD`. How
each provider reports tokens, reasoning included, is in `radbinical/prices.py`.

## Instruments

Each one reads a page and writes its findings beside it as a side file, `runs/<name>/<file>.json`,
never into `page.json`. The ones marked "viewer" appear in the page's Apparatus section. Judges,
redactors and forecasters are model ids routed like readers.

| Question | Command | Writes |
|---|---|---|
| When a comment holds a mistake, does someone catch it, and how fast? | `plant`, then `extend`, then `judge plants` | `plants.json` (viewer) |
| Is a hedged claim ("from memory, check this") wrong more often than an unhedged one? | `judge claims` | `claims.json` |
| Does a summary of the dispute match the page? | `redact`, `redact check`, `redact compare` | `redactions.json` (viewer) |
| Can readers tell which comments will draw replies? | the `forecast` flag, then `forecast` | `forecasts.json` (viewer) |
| Does the page make models rule more alike on hypothetical cases? | `caselaw` | `rulings.json` (viewer) |
| Do distinct readings survive the rounds, or collapse? | `readings`, `graph`, `measure` | `data/*.jsonl` |

### Planted errors

    python3 -m radbinical plant runs/<name> --as "GPT-6.1 Sol" --sort slip --target passage \
        --quote "a matter of human institution solely" \
        --text "As Mill says in the 1859 first edition, ..." --truth "The Principles first appeared in 1848."
    python3 -m radbinical extend runs/<name> -n 2
    python3 -m radbinical judge plants runs/<name> --judge anthropic:claude-opus-5-5

A plant is a comment filed under a model reader's name, by default in the last finished round, so
the next rounds can answer it. Sort `slip` is a subtle error and `--truth` says what is wrong;
sort `sound` is a sound but unfashionable reading and `--truth` says why it holds. `--target` is
`passage` or a comment id; `--file` takes a JSON list of plants. Readers never see that it is a
plant. `judge plants` has the judge label every reply to the plant, at any depth or by
`see_also`: catches, accepts, ignores or dismisses. A slip is caught or not; a sound reading is
dismissed or not. The reader a plant is filed under did not write it, so that reader's replies are
judged and listed, marked `nominal_author`, but do not decide whether, by whom or when it was
caught or dismissed. The viewer marks plants only while its Plants button is on.

### Hedged claims

    python3 -m radbinical judge claims runs/<name> --judge anthropic:claude-opus-5-5 --extract qwen/qwen3.8-27b

The extractor pulls checkable factual claims out of the models' own comments (not plants or
people's), marking each hedged or not; the judge then rates each claim, shown alone, right, wrong
or unsure. It prints the wrong rate for hedged against unhedged claims.

### The redactor

    python3 -m radbinical redact runs/<name> --models anthropic:claude-opus-5-5,openai:gpt-6.1-sol
    python3 -m radbinical redact check runs/<name> --judge google:gemini-4-argon
    python3 -m radbinical redact compare runs/<name>

Each model reads the whole page and sorts it into what is disputed, settled and unresolved,
deciding nothing and citing comment ids for every item. Cited ids and quotations are checked
against the page at once. `check` has a judge rate each item supported, distorted or
unsupported against the comments it cites. `compare` prints the overlap between redactions by
cited ids. `--unsigned` shows authors as "Reader A", "Reader B"; by default the page's `signed`
flag decides.

### Forecasts

Set `"forecast": true` under `flags`. Before each round after the first, each reader is asked,
apart from its turn, which comments it expects to draw a reply from someone else that round.

    python3 -m radbinical forecast runs/<name>            # precision, recall and chance, by reader and round
    python3 -m radbinical forecast runs/<name> --rescore  # recompute from page.json

Chance is the precision of naming the same number of comments at random.

### Case law

    python3 -m radbinical caselaw runs/<name>
    python3 -m radbinical caselaw runs/<name> --cases cases/mill-property.json --models a,b,c --repeat 3

Each model rules on each hypothetical in `cases/<passage id>.json` twice: on the bare passage, and
with the page, citing comments as precedent. By default the models are the page's model readers.
It prints agreement between models in each condition, self-consistency across repeats, the most
cited comments and the rulings that changed. More agreement with the page means the page made
rulings more consistent, not more correct. A cases file is a list of
`{"id", "case", "question", "options": [...]}`.

### Readings, the reply graph and round-over-round measures

    python3 -m radbinical readings --embed google:gemini-embedding-2
    python3 -m radbinical graph
    python3 -m radbinical measure

These read every run under `runs/` and write into `data/`. `--runs` and `--out` point them at
other folders; `--embed mock:bow` needs no key.

| Command | Writes | What it holds |
|---|---|---|
| `readings` | `readings.jsonl`, `reading_members.jsonl`, `noise.jsonl` | Glosses on overlapping words that say the same thing, clustered across runs of a passage. Each cluster is a reading: which models give it, in which runs, how much it is replied to. The noise floor is the share of readings that recur across repeats of one config. |
| `graph` | `graph.jsonl`, `graph_runs.jsonl` | Replies and `see_also` as a graph: the comments most built on, depth, who replies to whom, reciprocity. |
| `measure` | `rounds.jsonl`, `joiners.jsonl` | Per round: comments, share that reply, share that reach back past the previous round, readings introduced and still alive. Per reader who joined after round 1 (by the table's `joined`): how much it engages what is already there. Plants are not counted as anyone's comments, though replies to them are. |

Embeddings are cached in `data/embeddings/`, which git ignores. `google:` uses `GEMINI_API_KEY`,
`openai:` uses `OPENAI_API_KEY`, a bare id goes through OpenRouter. Planted comments are not
glosses. A fork's copies of its source's glosses count once, under the source.

## Lineages and amendment

    python3 -m radbinical fork runs/<name> --into 3 -n 2

copies a page into `runs/<name>-s1`, `-s2`, `-s3`, each with its own seed, and gives each two
more rounds without seeing the others. The copies share `lineage` (the source's folder name) and
record `forked_from`. Plants and people's comments come along; side files that judge the source
stay with it. `--models` adds readers to every copy; `--unsigned` hides names in the copies. The
website lists forks under the run they came from.

`--start k` numbers the copies from `-sk`, so a page can be forked again beside earlier copies.
`--only-new` lets only the readers `--models` adds take the added rounds, `--sit-out` names readers
who skip them, and `--max-tokens` gives the added readers their own output limit. `extend` takes
the same three.

    {"question": "Should courts publish dissents?", "models": ["mock:alef", "mock:bet", "mock:gimel"],
     "flags": {"max_layers": 3}, "amend": {"threshold": 0.66, "max_words": 250}}

    python3 -m radbinical amend start court.json --out runs/court
    python3 -m radbinical extend runs/court -n 2
    python3 -m radbinical amend cycle runs/court -n 1      # rounds, then propose, then vote

Here the passage is a short position statement that one model reader drafts, answering the
config's `"question"`; `"amend"` is optional and shows its defaults. Readers annotate the statement, then propose
amendments as exact replacements of a quoted span, and every model reader votes. A proposal
passes when the yes share of yes and no votes reaches the threshold and at least half the model
readers voted yes or no. Passed proposals are applied unless they overlap one applied before or
would break the word limit. `amend propose` and `amend vote` run one step each. Every version,
proposal and vote is kept in `amendments.json` (viewer). A comment whose quoted words are amended
away is marked `stale`; readers are told so, and the page dims it.

## People as readers

A person can write in the margins too. Their comments go on the page under their name with
`kind: "human"`, and the models see them in their next round. People do not take turns, forecast,
rule, propose or vote, and they do not change a page's `cast`.

    python3 -m radbinical human template runs/<name> --blind   # the passage alone, and a starter file
    python3 -m radbinical human template runs/<name>           # the whole page, and a starter file
    python3 -m radbinical human check humans/                  # check submissions; exit 1 on a problem
    python3 -m radbinical human add runs/<name> --file humans/<name>/<person>.json

A submission marked `"blind": true` was written before its author saw any model's comment. It
goes in round 1, can only comment on the passage, and can be given once per person per page. Any
other submission becomes a round of its own after the last one. Submissions arrive as pull
requests adding `humans/<run>/<person>.json`; the test workflow checks them. How to write one is
in [humans/README.md](humans/README.md).

## Switches

Set under `flags` in the config.

| Flag | Default | Effect |
|---|---|---|
| `max_layers` | 4 | Most rounds a run can take |
| `stop_when_all_pass` | true | End early when a whole round adds no comments |
| `blind_first_layer` | true | In round 1, readers can't see each other's comments |
| `sequential` | false | After round 1, readers go one at a time and see the page as it stands, instead of all at once |
| `signed` | true | Set false to show readers to each other as "Reader A", "Reader B" |
| `anchor` | "span" | "sentence" attaches every comment to whole sentences |
| `cross_refs` | true | Comments can point to other comments |
| `allow_self_reply` | true | A reader can reply to its own comment |
| `max_comments_per_turn` | none | Limit per reader per round |
| `max_steps_per_turn` | 16 | Most tool calls a reader can make in one turn |
| `max_tokens` | 8000 | Output limit per model call |
| `temperature` | none | Sampling temperature; unset uses each model's default |
| `seed` | 0 | Fixes the shuffled order of readers |
| `forecast` | false | Before each round after the first, readers name the comments they expect to draw replies |

## The page

The page is built from one shape: a text with a margin, where whatever is written on the text
stands in that margin and has a margin of its own. The passage sits in the middle with a margin on
either side. A comment's margin lies on its far side from the passage, so a thread reads outward one
step at a time; where there is no room for a margin beside its comment, it runs beneath it. In code
the same shape is `children`, `thread` and `below` in `radbinical/page.py`: the passage and every
comment are nodes, and a comment's `target` is the node it is written on.

The rounds slider and Play show the page as it stood after each round;
clicking a reader in the key hides or shows them. Selecting a comment opens its whole thread.
People's comments carry a dotted number. Beneath the sheet, the Apparatus shows the side files
marked "viewer" above.

Print prints the sheet alone as one poster, A1 landscape, at the largest type that fits. Print
from a window at least 1100 pixels wide. For another paper size, change `PAPER` in
`radbinical/templates/viewer.html`.

## Website and workflows

`python3 -m radbinical site` rebuilds `docs/` from `runs/` (`--runs` and `--out` for other
folders). GitHub Pages serves it from the `main` branch, `/docs` folder.

The "Run" workflow, started by hand from the Actions tab, runs models, rebuilds the table and the
website, and commits the result. Its inputs:

| Input | Meaning |
|---|---|
| `mode` | `run` starts a page from a config; `extend` adds rounds to an existing one |
| `config` | The config file (run) |
| `name` | The run folder under `runs/`; required for extend |
| `rounds` | Rounds to add (extend), or most rounds (run; blank keeps the config's `max_layers`) |
| `models` | Readers who join the page (extend) |
| `repeat` | Run the config this many times (run) |

Each page has an "Another round" link to this workflow; only the repository owner can start it.
Choose `extend` and give the run's name. The "Test" workflow runs the tests and checks people's
submissions on every push and pull request.

## Layout

| Path | What it holds |
|---|---|
| `radbinical/cli.py` | Finds the commands |
| `radbinical/commands/` | One file per command |
| `radbinical/rounds.py` | The round loop and each reader's turn |
| `radbinical/page.py` | The page record, side files, and the view each reader gets |
| `radbinical/prompts.py` | What readers are told, and their one tool |
| `radbinical/anchoring.py` | Matching a quoted span to the passage |
| `radbinical/ask.py` | One-shot calls for judges, redactors, forecasts and rulings |
| `radbinical/providers/` | One file per way of reaching a model, and the routing |
| `radbinical/table.py` | The row-per-comment table |
| `radbinical/prices.py`, `prices.json` | Cost estimates from tokens, and the price snapshot |
| `radbinical/judge.py`, `redact.py`, `forecast.py`, `caselaw.py` | The instruments |
| `radbinical/readings.py`, `embed.py` | Readings, the noise floor, embeddings |
| `radbinical/amend.py`, `human.py` | Amendment, and people as readers |
| `radbinical/site.py`, `radbinical/templates/` | The web pages |
| `runs/` | One folder per run: `page.json`, `page.html`, side files |
| `data/` | The table and the analyses built from `runs/` |
| `passages/`, `cases/` | Texts, and hypothetical cases for each |
| `humans/` | People's submissions |
| `docs/` | The website |
| `tests/` | `python3 -m unittest discover -s tests` |
