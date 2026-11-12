# Radbinical

Several language models read the same passage and write comments in its margins. Then they read
each other's comments and write on those, round after round, until nobody has more to add or the
round limit is reached. Nothing is scored.

Pages so far: https://asavs.github.io/RADBINICAL/

What the first experiments on it showed is in [FINDINGS.md](FINDINGS.md). The instruments they
used (planted errors, redactors, forecasts, case law, readings, forks and amendment) are not in
this tree; they are at tags `0.4`, as first run, and `0.5`, carried onto the present protocol.

## Run it

    python3 -m radbinical run config.json

This writes `runs/<name>/page.json`, the full record, and `runs/<name>/page.html`, a page you can
open in a browser. Python 3.10 or later; no packages needed unless you call Anthropic directly
(`pip install anthropic`).

    python3 -m radbinical run config.mock.json                       # no keys; placeholder comments
    python3 -m radbinical run config.read.native.json --out runs/read-04   # choose the folder
    python3 -m radbinical extend runs/<name> -n 2                    # two more rounds
    python3 -m radbinical extend runs/<name> -n 1 --models x-ai/grok-4.7   # another reader joins
    python3 -m radbinical extend runs/<name> -n 1 --models qwen/qwen3.8-27b --only-new --max-tokens 40000
    python3 -m radbinical extend runs/<name> -n 2 --sit-out "Kimi K3"      # Kimi skips these rounds
    python3 -m radbinical render runs/<name>                         # rebuild page.html
    python3 -m radbinical site                                       # rebuild docs/ for the website

    python3 -m radbinical check config.json                          # can every reader be reached?

Every command explains itself with `-h`. `run` and `extend` first ask every reader for one word,
with the output limit a round would use, and start nothing if one cannot be reached: a provider
out of credit, a key with no quota for the model, or a model its provider has retired would
otherwise fail every turn and leave the page a voice short. `--no-check` skips that.

## Write on a page

    python3 -m radbinical serve              # http://127.0.0.1:8000
    python3 -m radbinical serve --env-keys   # readers may use the keys in this machine's .env

The first page is the library: the texts in `passages/`, each with the title and source
`passages/library.json` gives it, and a form for a text of your own. Choosing one opens a bare
page on it, with nothing in the margins. From there:

- **Ask models** names the models that take a round. They answer at the same time, each seeing
  the page as it stood when they were asked, and comment where they like. Any model id can be
  typed in; the ones offered are in `radbinical/roster.json`.
- **Select words**, in the passage or in a comment in the margins, and choose **Add comment** to
  write on them yourself or **Request comment** to ask models for one comment on exactly those
  words. A model asked this way writes its answer in the usual form and may decline; what it writes
  is put on the words selected, so words that occur twice are not mistaken for each other.
- Opening a comment's thread gives **Reply**, **Ask a model** and **Remove** under each comment.
  A removed comment is marked `hidden` in `page.json`: it leaves the page and is no longer shown to
  readers, and stays in the record.
- **Settings** holds your name, your provider keys, and whether models are told who wrote each
  comment (the page's `signed` flag).

Every ask is one round, so the rounds slider plays the page back in the order it was written.
While models are reading, the bar says who, and what the page has cost so far.

Keys are kept in the reader's browser and sent with each request; the server uses them for that
request's calls and writes them nowhere. The keys in the server's own `.env` are used only with
`--env-keys`. A maker's model normally goes only to its maker's API (see Readers and keys); a
reader who has given an OpenRouter key and not the maker's has it sent through OpenRouter, and the
page records the reader's model as `openrouter:<id>`.

Pages are kept in `pages/` (`--pages` for another folder), each as `page.json` in a folder named
by a long random id. That id is the page's address, `/p/<id>`, and is all anyone needs to read the
page or write on it; there are no accounts. A served page is the same record as a run, so
`render`, `extend` and the table work on its folder.

To let other machines reach it, give `--host 0.0.0.0` and a port. On a tailnet that is enough. On
the open internet put it behind something that provides HTTPS, since keys travel to it, and leave
`--env-keys` off.

## A turn

Every reader takes its turn the same way, whatever its model can do. It is shown the passage and
the margins as they stand, each comment beneath what it is written on, and answers once. Its answer
holds a block for each comment it wants to make, or none:

    <comment on="passage">
    <quote>the exact words it is on</quote>
    the comment
    </comment>

`on` names the node whose margin the comment goes in: `passage`, or a comment's id such as `c7`.
On the passage the quote is required and must be found there; on a comment it is optional.
`see="c2 c5"` points at other comments. What the answer says outside its blocks is kept in the
log as `closing` and does not go on the page.

A comment that cannot be recorded (its quote is not in the passage, or nothing has the id it
names) is sent back with the reason, together with any others refused in the same answer, and the
reader may write them again in one more answer. That is the whole turn: one answer, or two. A
reader is free to say again what it has already said; nothing refuses a repeat, and the table
marks it (`repeat_of`).

Each turn's entry in the page's `log` carries `replies`, the number of answers it took, and
`refused`, the comments still not recorded at the end. A turn in which the reader was asked about
particular words (see Write on a page) also carries `asked`, the node and the words.

## Readers and keys

Each entry under `models` in the config is one reader. A prefix sends it to that provider; a bare
OpenRouter-style id (`vendor/model`) goes to its maker's own API when the maker is OpenAI,
Anthropic, Google, xAI or NVIDIA, and otherwise through a shared provider: Nous if its key is set,
else OpenRouter.

OpenAI's, Anthropic's, Google's and xAI's models are native: they are sent to their maker or not
at all. Without the maker's key such a reader stops with a message naming it, and a failure at the
maker's API is not retried through a shared provider. Only an id that itself begins `openrouter:`
or `nous:` sends one of them through a shared provider.

| Reader written as | Goes to | Key |
|---|---|---|
| `qwen/qwen3.8-27b` | Nous, or OpenRouter | `NOUS_API_KEY`, `OPENROUTER_API_KEY` |
| `anthropic/claude-opus-5.5` | Anthropic, only | `ANTHROPIC_API_KEY` |
| `openai/gpt-6.1-terra` | OpenAI, only | `OPENAI_API_KEY` |
| `google/gemini-4-argon` | Google, only | `GEMINI_API_KEY` |
| `x-ai/grok-4.7` | xAI, only | `XAI_API_KEY` |
| `nvidia/nemotron-3-ultra-550b-a55b` | NVIDIA if its key is set, else as the first row | `NVIDIA_API_KEY` |
| `openai:gpt-6.1-sol` | OpenAI | `OPENAI_API_KEY` |
| `anthropic:claude-opus-5-5` | Anthropic | `ANTHROPIC_API_KEY` |
| `google:gemini-4-argon` | Google | `GEMINI_API_KEY` |
| `nvidia:nvidia/nemotron-3-ultra-550b-a55b` | NVIDIA | `NVIDIA_API_KEY` |
| `openrouter:nousresearch/hermes-4-405b` | OpenRouter, always | `OPENROUTER_API_KEY` |
| `nous:moonshotai/kimi-k3` | Nous, always | `NOUS_API_KEY` |
| `mock:anything` | No call; placeholder comments | none |

Ids with a variant suffix such as `:free`, and OpenAI's open-weight `gpt-oss` models, which their
makers' own APIs do not serve, always go through the shared provider. Each turn records the provider it went through as `via` in the page's log. The rules
live in `radbinical/providers/__init__.py`.

On your machine, copy `.env.example` to `.env` and fill in the keys you use; `.env` is ignored by
git, and a key already set in your shell wins. On GitHub, add them under Settings → Secrets and
variables → Actions with the same names.

`"max_tokens"` can be set per reader, and `"name"` sets how it appears on the page.

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
| `data/comments.jsonl` | comment | run, passage, cast, group, model, reader, round, id, parent, root, depth, start, end, quote, text, see_also, kind, repeat_of |
| `data/runs.jsonl` | run | passage, cast, group, readers, flags, rounds, comments, cost, cost_estimated, started |

A reply's start and end are its root's span on the passage. `kind` is `"human"` for a person's
comment and empty for a model's. `repeat_of` is the id of the first earlier comment in which the
same reader wrote the same words, wherever on the page either was put; empty when the comment is
not a repeat. Each reader in a run's row carries `joined`, the round it entered the page: a model
reader's first turn in the log, whether or not it commented, and a person's first comment. `cost`
adds up the cost of every turn, and `cost_estimated` is the part of it estimated from tokens (see
Cost below). The table is rebuilt from `runs/` each time; `page.json` stays the record.

## Cost

OpenRouter and Nous report what each call cost. Anthropic, OpenAI, Google and NVIDIA report
tokens only, so a call to one of them is priced from `radbinical/prices.json`, a snapshot of
OpenRouter's public price list, and its usage is marked `cost_estimated`. A model the snapshot
does not list gets no cost. The table prices logged turns that carry tokens but no cost the same
way when it reads them.

    python3 -m radbinical prices                       # refresh prices.json from OpenRouter; no key
    python3 -m radbinical spend                        # reported, estimated and sum, per run and in total
    python3 -m radbinical spend --since 2026-11-10     # runs started at or after this

`spend` counts each page's log; its last line is `total <number> USD`. How
each provider reports tokens, reasoning included, is in `radbinical/prices.py`.

## Joining and sitting out

`extend --models` adds readers to a page. `--only-new` lets only those readers take the added
rounds, `--sit-out` names readers who skip them, and `--max-tokens` gives the added readers their
own output limit.

## People as readers

A person can write in the margins too. Their comments go on the page under their name with
`kind: "human"`, and the models see them in their next round. People do not take turns, and they
do not change a page's `cast`.

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
| `max_tokens` | 8000 | Output limit per model call |
| `temperature` | none | Sampling temperature; unset uses each model's default |
| `seed` | 0 | Fixes the shuffled order of readers |

## The page

The page is built from one shape: a text with a margin, where whatever is written on the text
stands in that margin and has a margin of its own. The passage sits in the middle with a margin on
either side. A comment's margin lies on its far side from the passage, so each side is ruled into
columns: the one beside the passage holds comments on the passage, the next comments on those, and
so on outward for as many removes as the page reaches. A comment always stands in the column of
its own remove, with empty columns beyond it if nobody has answered; only where another column
would be too narrow to read does a margin run beneath its comment. In code
the same shape is `children` and `thread` in `radbinical/page.py`: the passage and every
comment are nodes, and a comment's `target` is the node it is written on.

Under every layout is one question, where on its text a comment is, answered the same way for
the passage and for a comment: a comment is on a node and, when it quotes, on a span of that node's
text; with no quote it is on the whole text. A comment on the passage stores its span as `start`
and `end`; a comment on a comment stores them when they were given exactly, as offsets into the
comment's text as shown, and is otherwise where its quote is first found. `radbinical/templates/kernel.js` holds the answer for
the viewer (`spanOf`), the cutting of a text into marked pieces (`pieces`) and the arithmetic of
writing each comment in the margin where its words end (`edge`, `stack`); none of it touches the page, and
`tests/test_kernel.py` runs it under Node.

On a wide screen the page opens pinned to the text, which is writing in the margins. The passage
has a margin all round it. A small mark, its writer's logo and its number, closes the words a
comment is on, and the comment is written at the edge of the passage nearest that mark (`edge`).

- Beside the passage, comments run down the margin in the order of their marks. Each is whole and
  starts level with its mark. The stretch of margin from a comment's mark to the next one's is the
  room it is entitled to, and where two comments would meet, the one with room to spare gives way
  (`stack`): the lower one starts lower if it can still end before the next mark, as the last one
  always can; otherwise the ones above it move up into free margin. It gives way by six lines or
  so on its own; of any more than that it takes half and the ones above move up by the other
  half. A comment that runs past the foot of the passage spreads into the room under it.
- Above or below the passage, a comment starts at its mark and runs to the right from there, as
  far as the next comment that starts there, or on into the right margin where that is clear.
- Each margin is in layers. Comments on the passage are in the layer next to it, and a reply is in
  the next layer out from the comment it is on: beside the passage, the next margin outward, level
  with its own mark in that comment; above or below, the next band outward.
- Beside the passage each layer is one unbroken margin, as wide all the way down, so how far
  out a comment stands always says which layer it is in. How wide each layer's margin is, is
  found, not fixed. A comment is as high as its words need at its margin's width, so a layer of
  long comments that push each other off their marks stands better in a wider margin, and a
  layer whose comments have room to spare can do with a thinner one. The search (`beside` in
  the viewer) starts from equal widths and moves a step of width from one layer to another,
  keeping a move when the comments then stand nearer their marks.

Nothing is cut or folded. Pin to text switches to the ruled columns described above, which a
narrow window and the printed sheet also use.

The rounds slider and Play show the page as it stood after each round;
clicking a reader in the key hides or shows them. Selecting a comment opens its whole thread.
People's comments carry a dotted number.

Print prints the column sheet alone as one poster, A1 landscape, at the largest type that fits,
whatever the window's width and whether or not Pin to text is on. For another paper size, change `PAPER` in
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
| `radbinical/preflight.py` | Asking each reader for one word before a run starts |
| `radbinical/page.py` | The page record, the tree of comments, and the view each reader gets |
| `radbinical/prompts.py` | What readers are told, and how their answer is read |
| `radbinical/anchoring.py` | Matching a quoted span to the passage |
| `radbinical/templates/kernel.js` | Where on its text a comment is, for the viewer's layouts |
| `radbinical/providers/` | One file per way of reaching a model, and the routing |
| `radbinical/table.py` | The row-per-comment table |
| `radbinical/prices.py`, `prices.json` | Cost estimates from tokens, and the price snapshot |
| `radbinical/human.py` | People as readers |
| `radbinical/site.py`, `radbinical/templates/` | The web pages |
| `radbinical/serve.py`, `templates/live.js`, `templates/library.html` | The server, a served page's controls, and the library |
| `radbinical/roster.json` | The models a served page offers |
| `runs/` | One folder per run: `page.json`, `page.html` |
| `pages/` | Served pages, one folder each; not in git |
| `data/` | The table built from `runs/` |
| `passages/` | Texts, and `library.json` with their titles and sources |
| `humans/` | People's submissions |
| `docs/` | The website |
| `tests/` | `python3 -m unittest discover -s tests` |
