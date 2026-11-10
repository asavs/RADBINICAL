# Radbinical

Several language models read the same passage and write comments in its margins. Then they read
each other's comments and write on those, round after round, until nobody has more to add or the
round limit is reached. Nothing is scored.

Pages so far: https://asavs.github.io/radbinical/

## Run it

    python3 radbinical.py run config.json

This writes `runs/<name>/page.json`, the full record, and `runs/<name>/page.html`, a page you can
open in a browser. Python 3.10 or later; no packages needed unless you call Anthropic directly
(`pip install anthropic`).

    python3 radbinical.py run config.mock.json                       # no keys; placeholder comments
    python3 radbinical.py extend runs/<name> -n 2                    # two more rounds
    python3 radbinical.py extend runs/<name> -n 1 --models x-ai/grok-4.7   # a new reader joins
    python3 radbinical.py site                                       # rebuild docs/ for the website

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

## Website

`python3 radbinical.py site` rebuilds `docs/`. GitHub Pages serves it from the `main` branch,
`/docs` folder.
