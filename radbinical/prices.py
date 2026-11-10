"""Dollar estimates for calls whose provider reports tokens but no cost.

The shared providers (OpenRouter, Nous) put `cost` in their usage. The makers' own APIs report
tokens only, so a call to Anthropic, OpenAI, Google or NVIDIA is priced here from `prices.json`,
a snapshot of OpenRouter's public model list in USD per token, keyed by OpenRouter-style id
(`python -m radbinical prices` refreshes it). A model is looked up by `providers.canonical`, so
"anthropic:claude-opus-5-5" and "anthropic/claude-opus-5.5" share one price. The estimate is
OpenRouter's rate for the model, which for most models is the maker's list price.

Tokens, as each session puts them in usage:

- Anthropic (providers/claude.py): `prompt_tokens` and `completion_tokens`, from the API's
  `input_tokens` and `output_tokens`. Output includes any thinking, which is billed as output.
- OpenAI's Responses API (providers/responses.py): `prompt_tokens` and `completion_tokens`, from
  `input_tokens` and `output_tokens`. Output includes reasoning tokens.
- Chat completions (providers/chat.py: OpenAI, NVIDIA, Google, OpenRouter, Nous): the provider's
  own usage, with `prompt_tokens`, `completion_tokens` and usually `total_tokens`; the nested
  details, such as `completion_tokens_details.reasoning_tokens`, are dropped when a turn's steps
  are summed (providers/http.py:add_usage). OpenAI and OpenRouter count reasoning inside
  `completion_tokens`, so the details are not added again.

Where `total_tokens` exceeds prompt plus completion, the difference is assumed to be reasoning
that `completion_tokens` left out, and is priced as completion. Where it does not, completion is
taken as it stands. `input_tokens` and `output_tokens` are read when the renamed keys are absent.
"""
import json
from pathlib import Path

from .providers import canonical

FILE = Path(__file__).with_name("prices.json")
SOURCE = "https://openrouter.ai/api/v1/models"
TABLE = None  # {canonical id: {"prompt": usd, "completion": usd}}; loaded from FILE on first use, or set by a test


def table():
    global TABLE
    if TABLE is None:
        TABLE = json.loads(FILE.read_text(encoding="utf-8"))["models"] if FILE.exists() else {}
    return TABLE


def tokens(usage):
    """(prompt, completion) tokens in a usage dict, or None if it reports none."""
    u = usage or {}
    p, c = u.get("prompt_tokens", u.get("input_tokens")), u.get("completion_tokens", u.get("output_tokens"))
    if not isinstance(p, (int, float)) and not isinstance(c, (int, float)):
        return None
    p, c = p or 0, c or 0
    t = u.get("total_tokens")
    if isinstance(t, (int, float)) and t > p + c:
        c = t - p
    return p, c


def price(model, usage):
    """The estimated USD cost of `usage` for `model`, or None if it has no tokens or the model no price."""
    rate, tk = table().get(canonical(model)), tokens(usage)
    if not rate or tk is None:
        return None
    return round(tk[0] * rate["prompt"] + tk[1] * rate["completion"], 8)


def complete(model, usage):
    """Sets `cost` to the estimate and `cost_estimated` to true on a usage dict that has tokens but
    no `cost`, when the model has a price. Changes the dict in place and returns it."""
    if isinstance(usage, dict) and "cost" not in usage:
        est = price(model, usage)
        if est is not None:
            usage["cost"], usage["cost_estimated"] = est, True
    return usage


def costs(usages):
    """(reported, estimated) USD over a list of usage dicts."""
    rep = est = 0.0
    for u in usages:
        if isinstance(u, dict) and isinstance(u.get("cost"), (int, float)):
            if u.get("cost_estimated"):
                est += u["cost"]
            else:
                rep += u["cost"]
    return round(rep, 6), round(est, 6)


def snapshot_text(models, fetched):
    """prices.json's text: models sorted by id, one per line."""
    lines = [f"  {json.dumps(k)}: {json.dumps(models[k])}" for k in sorted(models)]
    return (f'{{"fetched": {json.dumps(fetched)}, "source": {json.dumps(SOURCE)}, "models": {{\n'
            + ",\n".join(lines) + "\n}}\n")


def from_listing(listing):
    """{id: {"prompt", "completion"}} from OpenRouter's /models answer, keeping models with a
    known, non-zero price (negative prices mean "varies" and are dropped)."""
    out = {}
    for m in listing.get("data") or []:
        pr = m.get("pricing") or {}
        try:
            p, c = float(pr.get("prompt")), float(pr.get("completion"))
        except (TypeError, ValueError):
            continue
        if m.get("id") and p >= 0 and c >= 0 and (p or c):
            out[m["id"]] = {"prompt": p, "completion": c}
    return out
