# Radbinical

Several language models read the same passage and write comments in its margins. Then they read
each other's comments and write on those, round after round, until nobody has more to add or the
round limit is reached. Nothing is scored.

Pages so far: https://asavs.github.io/radbinical/

## Run it

    python3 -m radbinical run config.json

This writes `runs/<name>/page.json`, the full record, and `runs/<name>/page.html`, a page you can
open in a browser. Python 3.10 or later; no packages needed unless you call Anthropic directly
(`pip install anthropic`).

    python3 -m radbinical run config.mock.json                       # no keys; placeholder comments
    python3 -m radbinical extend runs/<name> -n 2                    # two more rounds
    python3 -m radbinical extend runs/<name> -n 1 --models x-ai/grok-4.7   # a new reader joins
    python3 -m radbinical site                                       # rebuild docs/ for the website

## Readers and keys

Each entry under `models` in the config is one reader. A bare id goes through OpenRouter; a prefix
sends it elsewhere.

| Reader written as | Goes to | Key |
|---|---|---|
| `qwen/qwen3.8-27b` | OpenRouter | `OPENROUTER_API_KEY` |
| `openai:gpt-6.1-sol` | OpenAI | `OPENAI_API_KEY` |
| `nvidia:nvidia/nemotron-3-ultra-550b-a55b` | NVIDIA | `NVIDIA_API_KEY` |
| `anthropic:claude-opus-5-5` | Anthropic | `ANTHROPIC_API_KEY` |

All four keys are read the same way. On your machine, copy `.env.example` to `.env` and fill in
the ones you use; `.env` is ignored by git. On GitHub, add them under Settings → Secrets and
variables → Actions with the same names, then start the "Run" workflow from the Actions tab. It
runs a config, rebuilds the website and commits the result.

A reader whose model can't call tools can be given `"protocol": "text"`; it then writes its
comments as tagged blocks in plain text. `"max_tokens"` can also be set per reader.

Each reader is shown with its maker's logo and brand colour, worked out from the model id. The
table is `radbinical/brands.json`; the logos are linked from the lobe-icons set, not stored here.
A reader whose maker isn't in the table gets a plain coloured dot. To set the maker by hand, add
`"brand": "nousresearch"` (any key from the table) to the reader.

## Your own passage

Put the text in `passages/` as plain text with a blank line between paragraphs, and set
`passage.file`, `passage.title` and `passage.source` in the config.

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

## Layout

| Path | What it holds |
|---|---|
| `radbinical/cli.py` | Commands |
| `radbinical/rounds.py` | The round loop and each reader's turn |
| `radbinical/page.py` | The page record and the view each reader gets |
| `radbinical/prompts.py` | What readers are told, and their one tool |
| `radbinical/anchoring.py` | Matching a quoted span to the passage |
| `radbinical/providers/` | One file per way of reaching a model |
| `radbinical/site.py`, `radbinical/templates/` | The web pages |
| `tests/` | `python3 -m unittest discover -s tests` |

## Website

`python3 -m radbinical site` rebuilds `docs/`. GitHub Pages serves it from the `main` branch,
`/docs` folder.
