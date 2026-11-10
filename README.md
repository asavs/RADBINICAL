# marginalia

Several models annotate one passage, then annotate each other's annotations, round by round.
The result is a page with the passage in the centre and the commentary in the margins.

    python3 marginalia.py run config.json          # needs OPENROUTER_API_KEY
    python3 marginalia.py run config.mock.json     # offline test, placeholder comments
    python3 marginalia.py extend runs/<dir> -n 2   # add rounds to an existing page
    python3 marginalia.py extend runs/<dir> -n 1 --models x-ai/grok-4.7   # a new reader joins
    python3 marginalia.py render runs/<dir>        # rebuild page.html from page.json

Each run writes `runs/<dir>/page.json` (the full record) and `page.html` (self-contained viewer).

To use your own text, put it in `passages/` as plain text with blank lines between paragraphs
and point `passage.file` at it.

## Switches (`flags` in the config)

| flag | default | meaning |
|---|---|---|
| `max_layers` | 4 | cap on rounds |
| `stop_when_all_pass` | true | end early when a whole round adds nothing |
| `blind_first_layer` | true | round 1 is independent: nobody sees anyone else |
| `sequential` | false | later rounds one reader at a time on the live page, instead of all at once |
| `signed` | true | false shows readers to each other as "Reader A", "Reader B" |
| `anchor` | "span" | "sentence" snaps every anchor to whole sentences |
| `cross_refs` | true | comments may point at other comments |
| `allow_self_reply` | true | a reader may reply to its own comment |
| `max_comments_per_turn` | null | per-reader, per-round limit |
| `temperature`, `seed` | null, 0 | sampling temperature; seed for turn order |

Model ids are OpenRouter ids. Prefix with `openai:` to call OpenAI directly (`OPENAI_API_KEY`).
