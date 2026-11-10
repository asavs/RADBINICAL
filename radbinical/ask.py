"""One-shot calls: a system prompt and one user message in, the model's answer out.

    text, usage = ask("qwen/qwen3.8-27b", system, user)
    obj, usage = ask_json("anthropic:claude-opus-5-5", system, user)

The model id is routed exactly as a reader's is (providers.route): a prefix such as "openai:",
"anthropic:", "google:", "nvidia:" or "mock:" picks the provider, and a bare OpenRouter id goes
to its maker when the maker's key is set, else to OpenRouter. `usage` is the provider's usage
dict (OpenRouter's includes `cost`) plus "via", the provider actually used; keep it, e.g. in a
side file's "usage" list.

"mock:<anything>" makes no call and is deterministic: if the user message has a line
`MOCK_REPLY: <text>`, the answer is <text> (the rest of that line, stripped); otherwise it is
MOCK_DEFAULT. Usage is {"via": "mock"}. So a test can write `MOCK_REPLY: {"verdict": "caught"}` into the
user message and get that JSON back from ask_json.

For tests that cannot put a line into the message, set HOOK to a callable
`HOOK(model, system, user, max_tokens, temperature) -> (text, usage)`; while it is set, every
ask (and ask_json) calls it instead of any model, mock included. Reset it to None afterwards.
"""
import json
import re

from .providers import open_session, split_model


MOCK_DEFAULT = "[mock] No answer."
HOOK = None

_MOCK_LINE = re.compile(r"^MOCK_REPLY:[ \t]*(.*)$", re.M)


def ask(model, system, user, max_tokens=4000, temperature=None):
    """Ask once, with no tools. Returns (text, usage)."""
    if HOOK is not None:
        return HOOK(model, system, user, max_tokens, temperature)
    if split_model(model)[0] == "mock":
        m = _MOCK_LINE.search(user)
        return (m.group(1).strip() if m else MOCK_DEFAULT), {"via": "mock"}
    flags = {"max_tokens": max_tokens, "temperature": temperature, "cross_refs": False}
    session = open_session({"model": model}, system, user, flags, tools=False)
    _, text, usage = session.step()
    return text, {**usage, "via": session.via}


def ask_json(model, system, user, max_tokens=4000, temperature=None):
    """Ask for JSON. Returns (the first JSON object or array in the answer, usage).

    The answer may wrap the JSON in a code fence or prose. Raises ValueError if nothing parses.
    """
    system = (system + "\n\n" if system else "") + "Answer with JSON only: one object or array, no other text."
    text, usage = ask(model, system, user, max_tokens, temperature)
    return extract_json(text, model), usage


def extract_json(text, source="the model"):
    """The first JSON object or array found in text."""
    dec = json.JSONDecoder()
    for m in re.finditer(r"[{\[]", text or ""):
        try:
            return dec.raw_decode(text, m.start())[0]
        except json.JSONDecodeError:
            continue
    raise ValueError(f"no JSON object or array in the answer from {source}: {(text or '')[:300]!r}")
