"""Reaching models. One Session class per provider, all with the same three moves:

    step()         -> (calls, text, usage)   calls = [(call_id, args_dict_or_None)]
    reply(results)                           results = [(call_id, message)]

With tools=False a session is a plain exchange: step() returns the answer as text and no calls.

`route(model)` decides where a model id goes, and is the only place that does:

- An explicit prefix wins: "openai:", "anthropic:", "google:", "nvidia:", "openrouter:", "mock:".
  If that maker's key is not set, the call goes through OpenRouter when OPENROUTER_API_KEY is set
  and the id has an OpenRouter form; otherwise route raises, naming the missing key.
- A bare OpenRouter id "vendor/name" whose vendor is openai, anthropic, google or nvidia goes
  straight to the maker when the maker's key is set ("anthropic/claude-opus-5.5" is sent to
  Anthropic as "claude-opus-5-5"). Ids with an OpenRouter variant suffix (":free", ":batch"),
  and OpenAI's open-weight gpt-oss models, which OpenAI's own API does not serve, stay on
  OpenRouter.
- Anything else goes to OpenRouter.

`canonical(model)` is the OpenRouter-style id, the same however the model was written.
"""
import re

from .chat import PROVIDERS, ChatSession, TextSession
from .claude import AnthropicSession
from .http import KEYS, api_key
from .mock import MockSession
from .responses import ResponsesSession


DIRECT = ("openai", "anthropic", "google", "nvidia")
KNOWN = set(PROVIDERS) | {"anthropic", "mock"}
_OPENROUTER_ONLY = re.compile(r"^openai/gpt-oss")


def split_model(model):
    """(prefix, rest) for an explicitly prefixed id, else ("openrouter", model). Ignores keys."""
    head, sep, rest = model.partition(":")
    return (head, rest) if sep and head in KNOWN else ("openrouter", model)


def _direct_name(vendor, name):
    """A maker's own id for the name part of its OpenRouter id."""
    if vendor == "anthropic":
        return name.replace(".", "-")
    return f"nvidia/{name}" if vendor == "nvidia" else name


def _openrouter_id(provider, name):
    """The OpenRouter id for a maker's own id, or None if it has none."""
    if provider == "anthropic":
        return "anthropic/" + re.sub(r"(?<=\d)-(?=\d)", ".", name)
    if provider == "nvidia":
        return name if name.startswith("nvidia/") else None
    return f"{provider}/{name}"


def route(model):
    """-> (provider, name to send it). See the module docstring for the rules."""
    head, name = split_model(model)
    if head == "mock" or model.startswith("openrouter:"):
        return head, name
    if head == "openrouter":  # a bare id
        vendor, slash, rest = model.partition("/")
        if slash and vendor in DIRECT and ":" not in rest and not _OPENROUTER_ONLY.match(model) and api_key(vendor):
            return vendor, _direct_name(vendor, rest)
        return "openrouter", model
    if api_key(head):
        return head, name
    back = _openrouter_id(head, name)
    if back and api_key("openrouter"):
        return "openrouter", back
    names = " or ".join(KEYS[head])
    raise RuntimeError(f"{model}: set {names}" + (", or OPENROUTER_API_KEY to go through OpenRouter" if back else
                                                   " (this id has no OpenRouter equivalent)"))


def canonical(model):
    """The OpenRouter-style id, so one model written two ways is one model."""
    head, name = split_model(model)
    if head == "mock":
        return model
    if head == "openrouter":
        vendor, slash, rest = name.partition("/")
        return _openrouter_id("anthropic", rest) if vendor == "anthropic" and slash else name
    return _openrouter_id(head, name) or model


def open_session(reader, system, user, flags, tools=True):
    """A session for the reader's model on the route `route` picks; `session.via` names it."""
    provider, name = route(reader["model"])
    max_tokens = reader.get("max_tokens") or flags["max_tokens"]
    if provider == "mock":
        s = MockSession(name, system, user)
    elif provider == "anthropic":
        s = AnthropicSession(name, system, user, flags, max_tokens, tools)
    elif provider == "openai" and (reader.get("protocol") != "text" or not tools):
        s = ResponsesSession(name, system, user, flags, max_tokens, tools)
    else:
        cls = TextSession if tools and reader.get("protocol") == "text" else ChatSession
        s = cls(provider, name, system, user, flags, max_tokens, tools)
    s.via = provider
    return s
