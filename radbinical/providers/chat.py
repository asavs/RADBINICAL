"""OpenAI-style chat completions: OpenRouter, NVIDIA, Google, and plain-text mode."""
import json
import re

from ..prompts import annotate_tool
from .http import post_json


PROVIDERS = {  # endpoint, name of the output-limit field
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "max_tokens"),
    "nous": ("https://inference-api.nousresearch.com/v1/chat/completions", "max_tokens"),  # takes OpenRouter-style ids
    "openai": ("https://api.openai.com/v1/chat/completions", "max_completion_tokens"),
    "nvidia": ("https://integrate.api.nvidia.com/v1/chat/completions", "max_tokens"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "max_tokens"),
}


class ChatSession:
    """OpenAI-style chat completions with native tool calls (OpenRouter, OpenAI, NVIDIA, Google)."""
    def __init__(self, provider, name, system, user, flags, max_tokens, tools=True):
        self.provider = provider
        self.url, self.cap = PROVIDERS[provider]
        self.name, self.flags, self.max_tokens = name, flags, max_tokens
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        self.tools = [annotate_tool(flags)] if tools else []

    def _send(self, with_tools=True):
        body = {"model": self.name, "messages": self.messages, self.cap: self.max_tokens}
        if with_tools and self.tools:
            body["tools"] = self.tools
        if self.flags["temperature"] is not None:
            body["temperature"] = self.flags["temperature"]
        data = post_json(self.url, self.provider, body)
        return data["choices"][0]["message"], data.get("usage") or {}

    def step(self):
        msg, usage = self._send()
        self.messages.append(msg)  # kept whole so any reasoning blocks the provider needs are replayed intact
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                calls.append((c["id"], json.loads(c["function"].get("arguments") or "{}")))
            except json.JSONDecodeError:
                calls.append((c["id"], None))
        text = msg.get("content") if isinstance(msg.get("content"), str) else ""
        return calls, text or "", usage

    def reply(self, results):
        for cid, res in results:
            self.messages.append({"role": "tool", "tool_call_id": cid, "content": res})


_BLOCK = re.compile(r"<annotate\b([^>]*)>(.*?)</annotate>", re.S | re.I)


_ATTR = re.compile(r"""(\w+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


class TextSession(ChatSession):
    """For models without reliable tool calling: comments are written as <annotate> blocks in plain text."""
    def step(self):
        msg, usage = self._send(with_tools=False)
        text = msg.get("content") if isinstance(msg.get("content"), str) else ""
        self.messages.append({"role": "assistant", "content": text or ""})
        calls = []
        for i, m in enumerate(_BLOCK.finditer(text or "")):
            attrs = {k.lower(): (a or b) for k, a, b in _ATTR.findall(m.group(1))}
            args = {"target": attrs.get("target", "passage"), "quote": attrs.get("quote", ""), "text": m.group(2).strip()}
            if attrs.get("see_also"):
                args["see_also"] = re.split(r"[,\s]+", attrs["see_also"].strip())
            calls.append((str(i), args))
        return calls, _BLOCK.sub("", text or "").strip(), usage

    def reply(self, results):
        lines = [res for _, res in results]
        self.messages.append({"role": "user", "content": "\n".join(lines) + "\n\nAdd more blocks if you wish, or reply without one to end your turn."})
