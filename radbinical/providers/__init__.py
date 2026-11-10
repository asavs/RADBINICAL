"""One Session class per provider, all with the same three moves:

    step()         -> (calls, text, usage)   calls = [(call_id, args_dict_or_None)]
    reply(results)                           results = [(call_id, message)]

A reader's model id picks the provider: "openai:...", "nvidia:...", "anthropic:...",
"mock:...", or a bare OpenRouter id. With tools=False a session is a plain exchange:
step() returns the model's answer as text and never any calls.
"""
from .chat import PROVIDERS, ChatSession, TextSession
from .claude import AnthropicSession
from .mock import MockSession
from .responses import ResponsesSession


KNOWN = set(PROVIDERS) | {"anthropic", "mock"}


def split_model(model):
    head, sep, rest = model.partition(":")
    return (head, rest) if sep and head in KNOWN else ("openrouter", model)


def open_session(reader, system, user, flags, tools=True):
    provider, name = split_model(reader["model"])
    max_tokens = reader.get("max_tokens") or flags["max_tokens"]
    if provider == "mock":
        return MockSession(name, system, user)
    if provider == "anthropic":
        return AnthropicSession(name, system, user, flags, max_tokens, tools)
    if provider == "openai" and (reader.get("protocol") != "text" or not tools):
        return ResponsesSession(name, system, user, flags, max_tokens, tools)
    cls = TextSession if tools and reader.get("protocol") == "text" else ChatSession
    return cls(provider, name, system, user, flags, max_tokens, tools)
