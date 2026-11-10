# Findings

What seven experiments measured when the instruments in [PLAN.md](PLAN.md) were first run on real models. Every number names the file it comes from. The data are small: three repeats at best, one judge, one passage per experiment. Read every figure below as a first measurement of an instrument, not as a result about models.

## The casts

The main cast in `config.json` and `config.read.json` is seven readers: Claude Opus 5.5 and GPT-6.1 Terra through their makers' APIs; Gemini 4 Argon, Grok 4.7, DeepSeek v4.1 and Kimi K3 through Nous; Hermes 4 405B through OpenRouter with the text protocol. Every reader has 16000 output tokens per call.

Only experiments 1 and 2 ran with the whole cast. The Nous balance ran out during the second Read repeat (HTTP 402, "Insufficient available credits"), and the OpenRouter balance shortly after. From then on Gemini could not be reached at all (it is configured as `nous:`, and direct Gemini chat returns 429), and Grok and Kimi could be reached only through OpenRouter, which refused them for lack of credit. Each later experiment says which readers took part.

## 1. Noise floor (Mill)

**Question.** Run the same cast on the same passage three times. How many readings recur?

**Run.** `config.json`, main cast, Mill, *Principles* II.1 §1, 4 rounds, n = 3 (`runs/mill-03-a`, `-b`, `-c`; 75, 79 and 93 comments). No reader failed for a provider reason. Hermes lost one turn of 12 (mill-03-a, round 3) by writing its comments as JSON.

A reading is a cluster of top-level glosses on overlapping spans whose Gemini embeddings have mean cosine at least *t* (`radbinical/readings.py`). The threshold was chosen by reading pairs of glosses from different runs on overlapping spans, four or five per band of cosine, on both passages. From 0.84 to 0.88 nearly every pair gave the same reading (12 of 14 read); from 0.80 to 0.84 about half did; below 0.80 few did. *t* = 0.84 is the default for `google:` embeddings. An example at 0.875, the same reading:

> GPT-6.1 Terra (mill-03-b/c3): "Once there" does important work: it holds the stock of goods fixed so that their allocation can be treated as a matter of choice.
>
> Gemini 4 Argon (mill-03-c/c13): This cleanly severs production from distribution, treating wealth as a heap of finished goods waiting at the end of a harvest to be divided up.

and one at 0.838 that is not the same reading: DeepSeek on where Laughlin's abridgement cuts the paragraph (mill-03-a/c72) against Opus on first occupancy as a side effect (mill-03-b/c7).

Mean pairwise Jaccard of the runs' sets of readings, and the range over the three pairs (`data/noise.jsonl` at 0.84; the other thresholds from `readings --threshold`):

| *t* | all rounds | round 1 (blind) | readings, all rounds | in all 3 runs | in 1 run only |
|---|---|---|---|---|---|
| 0.80 | 0.64 (0.54 to 0.75) | 0.69 (0.58 to 0.78) | 25 | 52% | 36% |
| **0.84** | **0.41 (0.37 to 0.44)** | **0.48 (0.41 to 0.57)** | 40 | 28% | 55% |
| 0.88 | 0.23 (0.21 to 0.27) | 0.42 (0.39 to 0.46) | 73 | 12% | 73% |

At 0.84, about half of what one run says in its blind round is said again in another run, and more than half of all readings appear in one run only. That is the floor: a reading that shows up in one run and not another is not evidence of anything until it beats these figures.

Most recurrence is a model repeating itself. Of the 18 readings found in two or more Mill runs, 14 recur with the same model in both runs, and 5 recur only that way (`data/reading_members.jsonl`). The figures therefore measure each model's run-to-run stability as much as agreement between models. Shared training is the other rival explanation for any agreement between models; nothing here separates the two.

## 2. Obscure passage (Read)

**Question.** Does a passage with no commentary tradition converge less than Mill?

**Run.** `config.read.json`, the same cast, Samuel Read, *Natural Grounds of Right to Vendible Property* (1829), II.9 §3, 4 rounds, n = 2 (`runs/read-01-a`, `-b`; 91 and 105 comments). The third repeat was stopped in its first round when Nous ran out of credit, and deleted. In read-01-b's last round Gemini and Kimi stopped mid-turn on 402 errors after 3 and 4 comments; in read-01-a's third round Kimi spent all 16000 tokens reasoning and wrote nothing.

| *t* | Mill, all rounds | Read, all rounds | Mill, round 1 | Read, round 1 |
|---|---|---|---|---|
| 0.80 | 0.64 (0.54 to 0.75) | 0.49 | 0.69 (0.58 to 0.78) | 0.57 |
| **0.84** | **0.41 (0.37 to 0.44)** | **0.34** | **0.48 (0.41 to 0.57)** | **0.42** |
| 0.88 | 0.23 (0.21 to 0.27) | 0.04 | 0.42 (0.39 to 0.46) | 0.04 |

Mean pairwise Jaccard; Mill's range is over its three pairs, Read has one pair (`data/noise.jsonl`, `data/reading_members.jsonl`).

At the calibrated threshold Read's single pair sits at or just below the bottom of Mill's range, so the two passages cannot be told apart there. The difference is at 0.88: Mill keeps 0.42 in its blind round, Read falls to 0.04. On Mill the same things are said in nearly the same words from run to run; on Read they are not. That fits the idea that a commentary tradition supplies stock phrasings, but it rests on one Read pair, on one embedding model, and on two passages that differ in length (352 and 444 words) and so in how densely glosses overlap.

## 3. Accumulation (a reader joins late)

**Question.** Does a new reader joining a finished page answer what is there, or gloss the text afresh? Does hiding authors change that?

**Run.** Qwen 3.8 27b joins six copies of read-01-a for one round, taking the only turn: three copies signed and three unsigned (`fork --models qwen/qwen3.8-27b --only-new --max-tokens 40000`, `--unsigned` for the second three; `runs/read-01-a-s1` to `-s6`). With the page's 16000 tokens Qwen reasoned to the limit and wrote nothing, so it was given 40000.

| | copies | comments | replies to a comment | passage glosses citing comments (`see_also`) | `see_also` per comment | mean age of what it engages, rounds |
|---|---|---|---|---|---|---|
| signed | 3 | 6 | 0 | 6 | 3.8 | 3.6, 2.4, 2.3 |
| unsigned | 3 | 7 | 1 | 6 | 3.6 | 3.3, 3.2, 2.9 |

From the six `page.json` files and `data/joiners.jsonl`.

`measure` reports that 100% of the joiner's comments engage existing comments, which is true and misleading: 12 of 13 are fresh glosses on the passage that list three or four earlier comments in `see_also`, and they reach back to rounds 1 and 2 as often as to round 4. The joiner writes its own reading and positions it against the margin, often in so many words: "No one has yet parsed this phrase, though c36 saw its work" (read-01-a-s6/c92). Hiding authors made no visible difference at n = 3 a side. The one reply, to Kimi's c87, corrects an attribution and is itself wrong: Kimi attributed the 1797 *Commentaries on the Law of Scotland Respecting Crimes* to Baron Hume, which is right; Qwen replied that they "are by Henry Erskine, Lord Kinnaird" (read-01-a-s6/c93).

## 4. Planted error and hedged claims

**Question.** When a comment holds a mistake, is it caught, and how fast? Is a sound but unfashionable reading dismissed? Are hedged claims wrong more often?

**Run.** On a copy of read-01-b (`runs/read-01-b-s1`), two plants in round 4, then two rounds. Gemini sat out; Grok and Kimi failed both rounds on OpenRouter 402s; so the rounds were taken by Opus, Terra, DeepSeek and Hermes. Judge: GPT-6.1 Sol, not in the cast.

- *Slip*, filed under Grok 4.7 (c106): Blackstone (*Commentaries* IV.2) allowed necessity to excuse a starving man's theft of food, so the law was never against him. Blackstone says the opposite: he reports the view of Grotius and Pufendorf, calls it "an unwarranted doctrine, borrowed from the notions of some civilians", and says English law admits no such excuse (checked against the Avalon Project text of IV.2).
- *Sound*, filed under Kimi K3 (c107): "open war" is a conservative argument, the right to relief as the price of property's security, bounded by "with as little hurt as he can".

| plant | replies | verdicts | outcome |
|---|---|---|---|
| slip c106 | 2 | 2 catches | caught in the next round, by Terra and Opus |
| sound c107 | 0 | none | neither dismissed nor taken up |

From `runs/read-01-b-s1/plants.json`. Opus, in the round after the plant:

> I think this gets Blackstone backwards. In Commentaries IV ch. 2 he does report the Grotius/Pufendorf view that extreme want excuses taking food, but then he rejects it for England. [...] So the juries Read describes were not applying a settled rule. They were doing something the doctrine refused to allow. (c110)

One slip, caught by two of the four readers left, is an existence proof that the page can correct a checkable error, not a catch rate. The sound plant turned out not to be unfashionable on this page: Opus had made nearly the same argument in round 1 ("He is making a bargain argument for the poor law", c7), so silence here may mean the point was already on the page. A fair test of dismissal needs a sound reading that the page has not already made.

*Claims.* `judge claims` on mill-03-b, extractor and judge GPT-6.1 Sol (`runs/mill-03-b/claims.json`):

| | claims | wrong | right | unsure | wrong rate |
|---|---|---|---|---|---|
| hedged | 16 | 0 | 15 | 1 | 0% |
| unhedged | 56 | 2 | 49 | 5 | 4% |

Two wrong claims in 72 is too few to compare rates. Both are about the text's own layout: Opus placing a sentence "two sentences after" another that it follows by five (c5), and Grok on where Laughlin's abridgement cuts (c54). Hedging is concentrated: 7 of Opus's 10 claims are hedged, none of Kimi's 21 (the most claims of any reader) and none of Gemini's 10. The judge rated each claim alone, from memory; one extracted "claim" was about other comments on the page, which the extractor's instructions exclude.

## 5. The redactor

**Question.** Do summaries of the dispute match the page, and do different models summarise it alike?

**Run.** mill-03-a redacted by Claude Opus 5.5, GPT-6.1 Terra and Nemotron 3 Ultra (not in the cast); each item judged by GPT-6.1 Sol against the comments it cites (`runs/mill-03-a/redactions.json`).

| redactor | items | disputed / settled / unresolved | quotes found | supported | distorted |
|---|---|---|---|---|---|
| Opus 5.5 | 16 | 8 / 4 / 4 | 16/16 | 15 | 1 |
| Terra | 20 | 6 / 3 / 11 | 19/20 | 20 | 0 |
| Nemotron 3 Ultra | 10 | 6 / 3 / 1 | 5/10 | 6 | 4 |

| pair, Jaccard of cited ids | all | disputed | settled | unresolved |
|---|---|---|---|---|
| Opus / Terra | 1.00 | 0.52 | 0.60 | 0.25 |
| Opus / Nemotron | 0.99 | 0.71 | 0.12 | 0.04 |
| Terra / Nemotron | 0.99 | 0.48 | 0.14 | 0.12 |

Four of the five distorted items are marked "settled", and the judge's reasons are of one kind: the cited comments agree on part and leave the rest open, and the item reports a consensus. Calling things settled is where redactors overreach. Overlap of all cited ids is uninformative, since every redactor cites nearly every comment on a 75-comment page; overlap by status is where they differ, and they differ most about what is settled and what is unresolved. Nemotron's quotations failed the mechanical check half the time, which needed no judge to find.

## 6. Forecasts and case law

*Forecasts.* **Run.** `config.hume-forecast.json`: Hume, *Enquiry* III.2, 3 rounds, forecasts on, with the four readers of the main cast still reachable (Opus, Terra, DeepSeek, Hermes); `runs/hume-fc-01`, 56 comments. Before rounds 2 and 3 each reader named the comments it expected to draw a reply from someone else.

| round | forecasts | named | hits | hits the forecaster made itself | precision | precision without those | chance |
|---|---|---|---|---|---|---|---|
| 2 | 4 | 27 | 12 | 4 | 0.44 | 0.30 | 0.23 |
| 3 | 4 | 22 | 9 | 3 | 0.41 | 0.27 | 0.10 |

From `runs/hume-fc-01/forecasts.json` (pooled over readers; chance is the share of seen comments that drew a reply). A third of the hits are forecasts the forecaster then fulfilled by replying. Without them precision is still above chance in both rounds, on 8 forecasts.

*Case law.* **Run.** `caselaw` on mill-03-a, six cases (`cases/mill-property.json`), five models (Opus 5.5, Terra, DeepSeek v4.1, Hermes 4, Nemotron 3 Ultra), one ruling each per condition; Gemini, Grok and Kimi were left out for want of credit (`runs/mill-03-a/rulings.json`).

| condition | rulings | agreement | mean pairwise |
|---|---|---|---|
| bare passage | 30 | 0.87 | 0.77 |
| with the page | 30 | 0.93 | 0.87 |

All 30 page rulings cite comments; 5 of 30 (model, case) rulings changed. Three of the five are one case, `volcanic-island`, where the majority flipped from A (4 to 1) to B (4 to 1). Agreement was already high on the bare text, there is one repeat, and more agreement means more consistent, not more correct.

## 7. Schools

**Question.** Do copies of one page, extended apart, drift into different readings?

**Run.** read-01-a forked into three lineages, two rounds each (`runs/read-01-a-s7`, `-s8`, `-s9`). Only Opus, Terra and DeepSeek took the rounds: Gemini, Grok and Kimi could not be reached, and Hermes sat out because OpenRouter could not hold three of its requests at once. DeepSeek stopped on a 402 after 4 comments in s9's last round.

| | s7 | s8 | s9 |
|---|---|---|---|
| new comments | 16 | 13 | 14 |
| new glosses on the passage | 1 | 7 | 6 |
| comments in the second round on threads begun after the fork | 1 of 8 | 5 of 6 | 4 of 7 |

| between lineages | mean pairwise Jaccard |
|---|---|
| old threads engaged, first round after the fork | 0.38 |
| old threads engaged, second round after the fork | 0.04 |
| readings of new glosses (12 readings, 2 in more than one lineage) | 0.08 |

Computed from `data/comments.jsonl` and `data/reading_members.jsonl` at *t* = 0.84; an "old thread" is one whose root is on read-01-a before the fork.

In their first round the lineages return to the same old threads about as often as two Mill repeats share readings (0.38 against Mill's 0.41). In their second they hardly overlap at all, because each lineage mostly answers its own new comments. Of 12 readings glossed after the fork, 8 are found in no other run of the passage. That is divergence, but the lineages are repeats with a shared start and three readers each, and nothing here distinguishes a school from the noise floor of experiment 1 begun at a later point.

## Instruments

What each instrument can be trusted for after meeting real models.

- **Readers on the text protocol.** Hermes 4, asked after its blocks whether it wanted to add more, kept writing until the 16-step cap, repeating itself and replying to its own new comments (33 and 35 comments a round in a trial run). A text-protocol turn is one reply, with failed blocks sent back at most twice. Hermes also leaves `<annotate>` tags unclosed (a block ends at the next block) and once wrote its comments as JSON (such a reply is sent back once; the Mill and Read runs carry the lost turn). Even so it repeats near-identical glosses on one sentence across rounds of a page (hume-fc-01) and praises what it replies to ("game-changing"). Its comment counts are not comparable with other readers'.
- **Reasoning models and output limits.** Qwen, DeepSeek and Kimi can spend an entire output limit on reasoning: Qwen at 8000 and 16000 tokens per turn, DeepSeek and Qwen on a redaction at 8000 and at 24000, DeepSeek on a forecast at 8000. An answer that hits the limit is an error that names the limit and still counts its cost. Neither Nous nor OpenRouter honoured a request to cap reasoning effort. One-shot calls get 8000 to 24000 tokens and readers 16000; `--max-tokens` sets a joining reader's own.
- **Anthropic** refuses a non-streamed request with a large output limit; Claude is streamed.
- **Shared providers.** A 402 arrives when requests already in flight hold the credit, not only when the balance is spent, and OpenRouter reserves each request's full output limit. A long page with seven readers in parallel at 16000 tokens each can exhaust a small balance in flight. Retries wait as long as `Retry-After` asks, for about five minutes. Several turns in the data above failed on credit, not on model behaviour; each is named in its experiment.
- **Embeddings.** Gemini's free tier counts every text against 100 a minute; the client waits out the quota. The reading threshold is calibrated for `gemini-embedding-2` only, and every recurrence figure moves by about a factor of two between 0.80 and 0.88.
- **Readings** cluster top-level glosses only. A comment that glosses the passage and cites four others counts as a fresh gloss for readings and as engagement for `measure`; the joiner figures need both views.
- **`judge plants`** sees only replies in a plant's thread or naming it in `see_also`; a reader who corrects the error in a fresh gloss is not counted.
- **`judge claims`** rates claims from the judge's memory with the claim alone, and the extractor sometimes extracts claims about the page itself.
- **Redactor overlap** by all cited ids saturates near 1 on a large page; read overlap by status.
- **Forecasts** need the self-fulfilled hits taken out, as above.
- **`measure`'s rounds rows** for a fork include the rounds it inherited from its source.
- **Assumptions from mock readers that were wrong:** that a reader asked "add more?" will stop; that an empty answer means "nothing to say"; that 8000 output tokens is plenty for a one-shot JSON answer; that a cosine of 0.8 means "same reading" (it merges distinct readings); that credit is a running total and not something held by requests in flight.

## Next

1. The third Read repeat and two more of each passage (n = 5 each) with the whole cast, so the Mill and Read figures both have ranges, and the same on a third passage with a known tradition. This needs credit on Nous or OpenRouter for four of the seven readers.
2. The planted-error run with the whole cast: three slips (factual, inferential, textual) and a sound reading checked beforehand against the page, each on three copies, so that a catch rate and a dismissal rate exist.
3. Recurrence within one model across runs against recurrence across models at a fixed threshold, to separate self-stability from agreement; and a second embedding model to test the threshold.
4. Schools with the whole cast and four rounds per lineage, against repeats started from the same page with no fork, which is the noise floor that drift must beat.

## Cost

Over the 16 runs added here, `python -m radbinical spend` counts 11.31 USD (12.86 total less the 1.56 of the three earlier runs): 4.65 reported by Nous and OpenRouter, 6.66 estimated from tokens for Anthropic, OpenAI and NVIDIA calls. About 1.1 USD more went on calls whose records are not under `runs/`: a shakedown kept outside the repository, runs deleted because a provider or a bug spoiled them, and single test calls. Altogether about 12.4 USD.
